import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import F
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from modeling.models import TradingModel

from . import services
from .forms import ModelSearchForm, initial_from_model, initial_from_search
from .models import ModelSearch, ModelSearchResult

logger = logging.getLogger(__name__)

# Accuracy columns worth showing per task (metrics-blob keys).
_REGRESSION_COLS = ("directional_accuracy", "skill_vs_naive", "r2", "mae")
_CLASSIFICATION_COLS = ("accuracy", "f1", "roc_auc", "precision")


def _fmt(value):
    if value is None:
        return ""
    try:
        return f"{float(value):.3f}"
    except (TypeError, ValueError):
        return str(value)


@login_required(login_url="marketdata:login")
@require_http_methods(["GET"])
def index(request):
    searches = ModelSearch.objects.select_related("best_result").prefetch_related("runs")
    return render(request, "modelsearch/index.html", {"searches": searches})


def _save(form, instance=None):
    data = form.cleaned_data
    obj = instance or ModelSearch()
    obj.name = data["name"]
    obj.base_model = data["base_model"]
    obj.feature_spec = data["feature_spec"]
    obj.target_spec = data["target_spec"]
    obj.train_start = data["train_start"]
    obj.train_end = data["train_end"]
    obj.holdout_fraction = data["holdout_fraction"]
    obj.search_space = data["search_space"]
    obj.mode = data["mode"]
    obj.max_candidates = data["max_candidates"]
    obj.random_seed = data["random_seed"]
    obj.auto_ensemble_top_k = data["auto_ensemble_top_k"]
    obj.scoring = data["scoring"] or ""
    obj.scoring_mode = data["scoring_mode"]
    obj.wf_scheme = data["wf_scheme"]
    obj.wf_train_span = data["wf_train_span"]
    obj.wf_test_span = data["wf_test_span"]
    obj.wf_step = data["wf_step"]
    obj.wf_gap = data["wf_gap"]
    obj.save()
    obj.instruments.set(data["instruments"])
    return obj


@login_required(login_url="marketdata:login")
@require_http_methods(["GET", "POST"])
def edit(request, pk=None):
    instance = get_object_or_404(ModelSearch, pk=pk) if pk else None

    # "Load from base model" - re-render the blank form prefilled, no validation.
    if request.method == "POST" and request.POST.get("op") == "load":
        base = TradingModel.objects.filter(pk=request.POST.get("base_model")).first()
        initial = initial_from_model(base) if base else None
        if base is None:
            messages.error(request, "Pick a base model first.")
        return render(
            request,
            "modelsearch/form.html",
            {"form": ModelSearchForm(initial=initial), "instance": instance},
        )

    if request.method == "POST":
        form = ModelSearchForm(request.POST)
        if form.is_valid():
            obj = _save(form, instance)
            messages.success(request, f"Saved search '{obj.name}'.")
            return redirect("modelsearch:detail", pk=obj.pk)
    else:
        if instance is not None:
            initial = initial_from_search(instance)
        elif request.GET.get("from"):
            base = TradingModel.objects.filter(pk=request.GET["from"]).first()
            initial = initial_from_model(base) if base else None
        else:
            initial = None
        form = ModelSearchForm(initial=initial)

    return render(request, "modelsearch/form.html", {"form": form, "instance": instance})


def _scatter(results):
    """Inline-SVG scatter of score (y) vs fit time (x) over a 320x160 box."""
    pts = [r for r in results if r.score is not None and r.fit_seconds is not None]
    if len(pts) < 2:
        return None
    xs = [r.fit_seconds for r in pts]
    ys = [r.score for r in pts]
    xlo, xhi = min(xs), max(xs)
    ylo, yhi = min(ys), max(ys)
    xspan = (xhi - xlo) or 1.0
    yspan = (yhi - ylo) or 1.0
    dots = [
        {
            "cx": round(10 + (r.fit_seconds - xlo) / xspan * 300, 1),
            "cy": round(150 - (r.score - ylo) / yspan * 140, 1),
            "pareto": r.is_pareto,
            "label": f"{r.estimator_key} score={r.score:.3f} fit={r.fit_seconds:.2f}s",
        }
        for r in pts
    ]
    return {"dots": dots, "xlo": xlo, "xhi": xhi, "ylo": ylo, "yhi": yhi}


@login_required(login_url="marketdata:login")
@require_http_methods(["GET", "POST"])
def detail(request, pk):
    search = get_object_or_404(ModelSearch.objects.prefetch_related("instruments", "runs"), pk=pk)

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "run":
            run = services.run_search(search, created_by=request.user)
            if run.status == run.Status.SUCCESS:
                messages.success(
                    request,
                    f"Search complete: {run.candidates_ok}/{run.candidates_total} candidates "
                    f"scored on {run.dataset_rows} rows.",
                )
            else:
                messages.error(request, f"Search failed: {run.error}")
            return redirect("modelsearch:detail", pk=pk)

        if action == "promote":
            result = get_object_or_404(
                ModelSearchResult, pk=request.POST.get("result"), search=search
            )
            try:
                model = services.promote_result(result, name=request.POST.get("name") or None)
            except Exception as exc:  # noqa: BLE001 - shown to the operator
                logger.exception("promote failed")
                messages.error(request, f"Could not promote: {exc}")
                return redirect("modelsearch:detail", pk=pk)
            messages.success(request, f"Created model '{model.name}'. Train it below.")
            return redirect("modeling:detail", pk=model.pk)

    latest_run = search.runs.first()
    results = []
    if latest_run is not None:
        results = list(latest_run.results.order_by(F("rank").asc(nulls_last=True), "-score"))
    task = search.task if search.target_spec else "regression"
    cols = _CLASSIFICATION_COLS if task == "classification" else _REGRESSION_COLS
    show_holdout_col = search.scoring_mode == ModelSearch.ScoringMode.WALK_FORWARD
    for r in results:
        blob = r.metrics or {}
        r.display_metrics = [_fmt(blob.get(c)) for c in cols]
        r.display_holdout_score = _fmt(blob.get("holdout_score"))

    return render(
        request,
        "modelsearch/detail.html",
        {
            "search": search,
            "runs": search.runs.all()[:15],
            "latest_run": latest_run,
            "results": results,
            "metric_cols": cols,
            "scatter": _scatter([r for r in results if r.status == ModelSearchResult.Status.OK]),
            "score_key": search.score_key() if search.target_spec else "",
            "show_holdout_col": show_holdout_col,
        },
    )
