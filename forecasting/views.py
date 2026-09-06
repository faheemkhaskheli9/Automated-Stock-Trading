"""Dashboard D7 - strict-path forecast backtest runner.

A thin UI over :func:`forecasting.services.run_forecast_backtest`: submit a
config, run one leakage-safe walk-forward synchronously, persist it as a
:class:`~forecasting.models.ForecastBacktestRun`, then browse the per-fold
table, skill badge, predicted-vs-actual chart and equity curve.

Server-rendered in the same style as the rest of Phase D (extends
``marketdata/base.html``, no htmx / Plotly). The ``backtesting`` app is the
counterpart for ``modeling.TradingModel`` artifacts.
"""

from __future__ import annotations

import csv
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from .forms import ForecastBacktestForm
from .models import ForecastBacktestRun

logger = logging.getLogger(__name__)


@login_required(login_url="marketdata:login")
@require_http_methods(["GET"])
def index(request):
    runs = ForecastBacktestRun.objects.all()[:100]
    return render(request, "forecasting/index.html", {"runs": runs})


@login_required(login_url="marketdata:login")
@require_http_methods(["GET", "POST"])
def new(request):
    form = ForecastBacktestForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        run = _run_forecast_backtest(**form.run_kwargs(), created_by=request.user)
        if run.status == ForecastBacktestRun.Status.SUCCESS:
            note = f"Ran {run.n_folds} folds, {run.n_predictions} OOS rows."
            if run.looks_leaky:
                messages.warning(request, note + " Result looks leaky - investigate.")
            else:
                messages.success(request, note)
        else:
            messages.error(request, f"Backtest failed: {run.error}")
        return redirect("forecasting:detail", pk=run.pk)
    return render(request, "forecasting/form.html", {"form": form})


def _run_forecast_backtest(**kwargs) -> ForecastBacktestRun:
    """Deferred import wrapper - keeps sklearn/statsmodels out of module import."""
    from .services import run_forecast_backtest as _run

    return _run(**kwargs)


def _polyline(values, lo, span):
    """SVG polyline points for ``values`` on a shared ``lo``/``span`` y-scale."""
    n = len(values)
    return " ".join(
        f"{20 + i * 960 / (n - 1):.1f},{220 - (v - lo) * 190 / span:.1f}"
        for i, v in enumerate(values)
    )


def _pred_vs_actual(predictions):
    scored = [
        p
        for p in predictions
        if isinstance(p.get("predicted"), (int, float))
        and isinstance(p.get("actual"), (int, float))
    ]
    if len(scored) < 2:
        return ""
    # Both lines must share one y-axis or the "predicted vs actual" comparison
    # hides systematic bias - pool the two series before scaling.
    vals = [v for p in scored for v in (p["predicted"], p["actual"])]
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1.0
    return {
        "predicted": _polyline([p["predicted"] for p in scored], lo, span),
        "actual": _polyline([p["actual"] for p in scored], lo, span),
    }


def _equity_points(curve):
    vals = [v for _, v in curve if isinstance(v, (int, float))]
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    return _polyline(vals, lo, (hi - lo) or 1.0)


@login_required(login_url="marketdata:login")
@require_http_methods(["GET"])
def detail(request, pk):
    run = get_object_or_404(ForecastBacktestRun, pk=pk)

    if request.GET.get("export") == "csv":
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="forecast-backtest-{run.pk}.csv"'
        writer = csv.writer(response)
        writer.writerow(["fold", "as_of", "target_date", "anchor", "predicted", "actual"])
        for p in run.predictions:
            writer.writerow(
                [
                    p.get("fold"),
                    p.get("as_of"),
                    p.get("target_date"),
                    p.get("anchor"),
                    p.get("predicted"),
                    p.get("actual"),
                ]
            )
        return response

    return render(
        request,
        "forecasting/detail.html",
        {
            "run": run,
            "chart": _pred_vs_actual(run.predictions or []),
            "equity": _equity_points(run.equity_curve or []),
        },
    )
