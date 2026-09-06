import csv
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from .forms import BacktestConfigForm
from .models import Backtest
from .services import run_backtest

logger = logging.getLogger(__name__)


@login_required(login_url="marketdata:login")
@require_http_methods(["GET"])
def index(request):
    backtests = Backtest.objects.select_related("model").prefetch_related("runs")
    return render(request, "backtesting/index.html", {"backtests": backtests})


@login_required(login_url="marketdata:login")
@require_http_methods(["GET", "POST"])
def edit(request, pk=None):
    instance = get_object_or_404(Backtest, pk=pk) if pk else None
    form = BacktestConfigForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        obj = form.save()
        messages.success(request, f"Saved backtest '{obj.name}'.")
        return redirect("backtesting:detail", pk=obj.pk)
    return render(request, "backtesting/form.html", {"form": form, "instance": instance})


def _chart_points(preds):
    scored = [p for p in preds if p.actual_value is not None and p.predicted_value is not None]
    if len(scored) < 2:
        return ""
    scored.sort(key=lambda p: (p.target_date, p.instrument_id))
    vals = [v for p in scored for v in (p.predicted_value, p.actual_value)]
    low, high = min(vals), max(vals)
    span = high - low or 1
    n = len(scored)
    return {
        "predicted": " ".join(
            f"{20 + i * 960 / (n - 1):.1f},{220 - (p.predicted_value - low) * 190 / span:.1f}"
            for i, p in enumerate(scored)
        ),
        "actual": " ".join(
            f"{20 + i * 960 / (n - 1):.1f},{220 - (p.actual_value - low) * 190 / span:.1f}"
            for i, p in enumerate(scored)
        ),
    }


def _equity_points(curve):
    if len(curve) < 2:
        return ""
    vals = [v for _, v in curve]
    low, high = min(vals), max(vals)
    span = high - low or 1
    n = len(curve)
    return " ".join(
        f"{20 + i * 960 / (n - 1):.1f},{220 - (v - low) * 190 / span:.1f}"
        for i, (_, v) in enumerate(curve)
    )


@login_required(login_url="marketdata:login")
@require_http_methods(["GET", "POST"])
def detail(request, pk):
    backtest = get_object_or_404(
        Backtest.objects.select_related("model").prefetch_related("runs"), pk=pk
    )
    if request.method == "POST" and request.POST.get("action") == "run":
        run = run_backtest(backtest, created_by=request.user)
        if run.status == run.Status.SUCCESS:
            messages.success(request, f"Ran {run.n_folds} folds, {run.n_predictions} predictions.")
        else:
            messages.error(request, f"Backtest failed: {run.error}")
        return redirect("backtesting:detail", pk=backtest.pk)

    latest = backtest.runs.first()
    folds = list(latest.folds.all()) if latest else []
    predictions = list(latest.predictions.select_related("instrument")) if latest else []

    if request.GET.get("export") == "csv" and latest:
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="backtest-{backtest.pk}.csv"'
        writer = csv.writer(response)
        writer.writerow(
            [
                "instrument",
                "fold",
                "as_of",
                "target_date",
                "predicted",
                "actual",
                "abs_error",
                "position",
            ]
        )
        for p in predictions:
            writer.writerow(
                [
                    p.instrument.symbol,
                    p.fold_index,
                    p.as_of.isoformat(),
                    p.target_date.isoformat(),
                    p.predicted_value,
                    p.actual_value,
                    p.abs_error,
                    p.position,
                ]
            )
        return response

    return render(
        request,
        "backtesting/detail.html",
        {
            "backtest": backtest,
            "runs": backtest.runs.all()[:20],
            "latest": latest,
            "folds": folds,
            "predictions": predictions[:300],
            "chart": _chart_points(predictions),
            "equity": _equity_points(latest.equity_curve) if latest else "",
        },
    )
