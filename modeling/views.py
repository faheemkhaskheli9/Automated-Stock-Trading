import csv
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from . import services
from .forms import ModelConfigForm, PredictForm
from .leaderboard import DEFAULT_WINDOW, WINDOW_CHOICES, build_leaderboard
from .models import TradingModel
from .registry import catalogue

logger = logging.getLogger(__name__)


@login_required(login_url="marketdata:login")
@require_http_methods(["GET"])
def index(request):
    models = TradingModel.objects.prefetch_related("instruments")
    return render(request, "modeling/index.html", {"models": models})


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

    predictions = list(model.predictions.select_related("instrument")[:200])
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
