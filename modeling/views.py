import csv
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Page, Paginator
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from . import services, symbol_selection
from .forms import ModelConfigForm, PredictForm
from .leaderboard import DEFAULT_WINDOW, WINDOW_CHOICES, build_leaderboard
from .models import TradingModel
from .registry import catalogue
from .weekday_suite import build_weekday_suite, suite_estimator_keys

logger = logging.getLogger(__name__)

MODEL_PAGE_SIZE = 25
PREDICTION_PAGE_SIZE = 50
# Rows fed to the predicted-vs-actual chart / rolling-MAE stat on the detail page.
PREDICTION_CHART_ROWS = 200


@login_required(login_url="marketdata:login")
@require_http_methods(["GET"])
def index(request):
    models = TradingModel.objects.prefetch_related("instruments")
    page = Paginator(models, MODEL_PAGE_SIZE).get_page(request.GET.get("page"))
    return render(request, "modeling/index.html", {"models": page, "page": page})


@login_required(login_url="marketdata:login")
@require_http_methods(["GET", "POST"])
def edit(request, pk=None):
    instance = get_object_or_404(TradingModel, pk=pk) if pk else None
    form = ModelConfigForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        obj = instance or TradingModel()
        obj.name = data["name"]
        obj.estimator_key = data["estimator"]
        obj.estimator_params = data["params_obj"]
        obj.feature_spec = data["feature_spec"]
        obj.target_spec = data["target_spec"]
        obj.train_start = data["train_start"]
        obj.train_end = data["train_end"]
        obj.holdout_fraction = data["holdout_fraction"]
        obj.save()
        obj.instruments.set(data["instruments"])
        messages.success(request, f"Saved model '{obj.name}'.")
        return redirect("modeling:detail", pk=obj.pk)
    return render(request, "modeling/form.html", {"form": form, "instance": instance})


@login_required(login_url="marketdata:login")
@require_http_methods(["GET", "POST"])
def detail(request, pk):
    model = get_object_or_404(TradingModel.objects.prefetch_related("instruments", "runs"), pk=pk)
    if request.method == "POST" and request.POST.get("action") == "train":
        run = services.train_model(model, created_by=request.user)
        if run.status == run.Status.SUCCESS:
            messages.success(request, f"Trained on {run.rows} rows ({run.feature_count} features).")
        else:
            messages.error(request, f"Training failed: {run.error}")
        return redirect("modeling:detail", pk=model.pk)

    prediction_qs = model.predictions.select_related("instrument")
    predictions = list(prediction_qs[:PREDICTION_CHART_ROWS])
    paginator = Paginator(prediction_qs, PREDICTION_PAGE_SIZE)
    page_param = request.GET.get("page")
    if page_param in (None, "", "1"):
        # Page 1's rows are already the head of `predictions` (same
        # ordering) - build the Page from that instead of re-querying the
        # same rows via paginator.get_page().
        prediction_page = Page(predictions[:PREDICTION_PAGE_SIZE], 1, paginator)
    else:
        prediction_page = paginator.get_page(page_param)
    if request.GET.get("export") == "csv":
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="model-{model.pk}-predictions.csv"'
        writer = csv.writer(response)
        writer.writerow(["instrument", "as_of", "target_date", "predicted", "actual", "abs_error"])
        for p in predictions:
            writer.writerow(
                [
                    p.instrument.symbol,
                    p.as_of.isoformat(),
                    p.target_date.isoformat(),
                    p.predicted_value,
                    p.actual_value,
                    p.abs_error,
                ]
            )
        return response

    scored = [
        p for p in predictions if p.actual_value is not None and p.predicted_value is not None
    ]
    points = ""
    if len(scored) >= 2:
        scored_ordered = sorted(scored, key=lambda p: p.target_date)
        vals = [v for p in scored_ordered for v in (p.predicted_value, p.actual_value)]
        low, high = min(vals), max(vals)
        span = high - low or 1
        n = len(scored_ordered)
        points = {
            "predicted": " ".join(
                f"{20 + i * 960 / (n - 1):.1f},{220 - (p.predicted_value - low) * 190 / span:.1f}"
                for i, p in enumerate(scored_ordered)
            ),
            "actual": " ".join(
                f"{20 + i * 960 / (n - 1):.1f},{220 - (p.actual_value - low) * 190 / span:.1f}"
                for i, p in enumerate(scored_ordered)
            ),
        }

    mae = (
        sum(p.abs_error for p in scored) / len(scored)
        if scored and all(p.abs_error is not None for p in scored)
        else None
    )
    return render(
        request,
        "modeling/detail.html",
        {
            "model": model,
            "runs": model.runs.all()[:20],
            "predictions": predictions,
            "prediction_page": prediction_page,
            "points": points,
            "rolling_mae": mae,
            "scored_count": len(scored),
        },
    )


@login_required(login_url="marketdata:login")
@require_http_methods(["GET", "POST"])
def predict_view(request, pk):
    model = get_object_or_404(TradingModel, pk=pk)
    form = PredictForm(request.POST or None, model=model)
    result = None
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            result = services.predict(
                model, data["instrument"], data["as_of"], target_date=data["target_date"]
            )
            messages.success(request, "Prediction stored.")
        except Exception as exc:  # noqa: BLE001 - shown to the operator
            logger.exception("Prediction failed")
            form.add_error(None, f"Could not predict: {exc}")
    return render(
        request,
        "modeling/predict.html",
        {
            "model": model,
            "form": form,
            "result": result,
            "predictions": model.predictions.select_related("instrument")[:50],
        },
    )


@login_required(login_url="marketdata:login")
@require_http_methods(["GET"])
def estimators(request):
    return render(request, "modeling/estimators.html", {"estimators": catalogue()})


@login_required(login_url="marketdata:login")
@require_http_methods(["GET"])
def leaderboard(request):
    """Rank active models by out-of-sample accuracy over a trailing window."""
    try:
        window = int(request.GET.get("window", DEFAULT_WINDOW))
    except (TypeError, ValueError):
        window = DEFAULT_WINDOW
    if window not in WINDOW_CHOICES:
        window = DEFAULT_WINDOW
    return render(
        request,
        "modeling/leaderboard.html",
        {
            "board": build_leaderboard(window_days=window),
            "window": window,
            "windows": WINDOW_CHOICES,
        },
    )


@login_required(login_url="marketdata:login")
@require_http_methods(["GET", "POST"])
def weekday_suite(request):
    """Auto-pick a well-covered instrument and train one of each applicable
    estimator on the Monday->Friday target, then compare their holdout
    accuracy - the "one action" path behind ``train_weekday_models``."""
    rankings = symbol_selection.score_instruments()
    result = None
    if request.method == "POST":
        symbol = request.POST.get("symbol", "").strip()
        instrument = None
        if symbol:
            instrument = next(
                (s.instrument for s in rankings if s.instrument.symbol == symbol), None
            )
            if instrument is None:
                messages.error(request, f"Unknown or unranked instrument {symbol!r}.")
                return redirect("modeling:weekday_suite")
        result = build_weekday_suite(instrument, created_by=request.user)
        for err in result.errors:
            messages.warning(request, err)
        if result.models:
            messages.success(
                request,
                f"Trained {len(result.models)} model(s) on {result.instrument.symbol}.",
            )
        rankings = symbol_selection.score_instruments()

    return render(
        request,
        "modeling/weekday_suite.html",
        {
            "rankings": rankings,
            "result": result,
            "estimator_keys": suite_estimator_keys(),
        },
    )
