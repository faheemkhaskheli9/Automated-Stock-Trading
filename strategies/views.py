import csv
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from marketdata.models import PriceBar
from marketdata.providers.base import Bar

from .backtesting.engine import run_backtest
from .forms import BacktestForm, ManualSignalForm, StrategyForm
from .models import ManualSignal, Strategy
from .registry import get_strategy_class

logger = logging.getLogger(__name__)

STRATEGY_PAGE_SIZE = 25
MANUAL_SIGNAL_PAGE_SIZE = 50


@login_required(login_url="marketdata:login")
@require_http_methods(["GET", "POST"])
def backtest(request):
    form = BacktestForm(
        request.POST if request.method == "POST" else None,
        allow_saved=request.user.has_perm("strategies.view_strategy"),
    )
    context = {"form": form}
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        rows = PriceBar.objects.filter(instrument=data["instrument"], timeframe="1d").order_by(
            "timestamp"
        )
        if data["start"]:
            rows = rows.filter(timestamp__date__gte=data["start"])
        if data["end"]:
            rows = rows.filter(timestamp__date__lte=data["end"])
        bars = [
            Bar(
                timestamp=r.timestamp,
                open=float(r.open),
                high=float(r.high),
                low=float(r.low),
                close=float(r.close),
                volume=r.volume,
                is_anomaly=r.is_anomaly,
            )
            for r in rows[:10001]
        ]
        if len(bars) < 3:
            form.add_error(
                None, "At least three daily bars are required. Import history in Market data first."
            )
        elif len(bars) > 10000:
            form.add_error(None, "Select a shorter date range (maximum 10,000 daily bars).")
        elif any(b.is_anomaly for b in bars):
            form.add_error(
                None,
                "This range contains flagged price anomalies. Review the data before backtesting.",
            )
        else:
            try:
                if data["model"].startswith("saved:"):
                    saved = form.saved.get(pk=int(data["model"].split(":")[1]))
                    strategy = saved.build()
                    if saved.key == "ml_model" and strategy._model is None:
                        raise ValueError("The saved ML model has no available model artifact.")
                else:
                    params = (
                        {"fast_period": data["fast_period"], "slow_period": data["slow_period"]}
                        if data["model"] == "ma_crossover"
                        else {}
                    )
                    strategy = get_strategy_class(data["model"])(**params)
                result = run_backtest(
                    strategy,
                    bars,
                    float(data["initial_cash"]),
                    next_open=True,
                    commission_bps=float(data["commission_bps"]),
                    slippage_bps=float(data["slippage_bps"]),
                )
            except Exception:
                logger.exception("Backtest failed")
                form.add_error(
                    None,
                    "Could not run this model. Check its configuration, model artifact, and price data.",
                )
            else:
                if request.POST.get("export") == "csv":
                    response = HttpResponse(content_type="text/csv")
                    response["Content-Disposition"] = 'attachment; filename="backtest-trades.csv"'
                    writer = csv.writer(response)
                    writer.writerow(
                        [
                            "entry_date",
                            "exit_date",
                            "shares",
                            "entry_price",
                            "exit_price",
                            "fees",
                            "net_pnl",
                        ]
                    )
                    for t in result.trades:
                        writer.writerow(
                            [
                                t.entry_time.isoformat(),
                                t.exit_time.isoformat(),
                                t.shares,
                                t.entry_price,
                                t.exit_price,
                                t.fees,
                                t.pnl,
                            ]
                        )
                    return response
                values = [v for _, v in result.equity_curve]
                low, high = min(values + [result.initial_cash]), max(values + [result.initial_cash])
                points = " ".join(
                    f"{20+i*960/(len(values)-1):.2f},{220-(v-low)*190/(high-low or 1):.2f}"
                    for i, v in enumerate(values)
                )
                context.update(
                    result=result,
                    points=points,
                    chart_low=low,
                    chart_high=high,
                    first=bars[0].timestamp,
                    last=bars[-1].timestamp,
                    count=len(bars),
                    return_pct=result.total_return * 100,
                    drawdown_pct=result.max_drawdown * 100,
                    win_pct=None if result.win_rate is None else result.win_rate * 100,
                    instrument=data["instrument"],
                    trades=result.trades[-200:][::-1],
                )
    return render(request, "strategies/backtest.html", context)


# --------------------------------------------------------------------------
# Strategy configuration (what run_trading_cycle executes)
# --------------------------------------------------------------------------
@login_required(login_url="marketdata:login")
@require_http_methods(["GET"])
def strategy_list(request):
    strategies = (
        Strategy.objects.select_related("account").prefetch_related("instruments").order_by("name")
    )
    page = Paginator(strategies, STRATEGY_PAGE_SIZE).get_page(request.GET.get("page"))
    return render(request, "strategies/strategy_list.html", {"strategies": page, "page": page})


@login_required(login_url="marketdata:login")
@require_http_methods(["GET", "POST"])
def strategy_edit(request, pk=None):
    instance = get_object_or_404(Strategy, pk=pk) if pk else None
    form = StrategyForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        obj = form.save()
        messages.success(request, f"Saved strategy '{obj.name}'.")
        return redirect("strategies:strategy_list")
    return render(request, "strategies/strategy_form.html", {"form": form, "instance": instance})


@login_required(login_url="marketdata:login")
@require_http_methods(["POST"])
def strategy_toggle(request, pk):
    obj = get_object_or_404(Strategy, pk=pk)
    obj.is_active = not obj.is_active
    obj.save(update_fields=["is_active", "updated_at"])
    messages.success(
        request,
        f"'{obj.name}' is now {'active' if obj.is_active else 'inactive'}.",
    )
    return redirect("strategies:strategy_list")


# --------------------------------------------------------------------------
# Manual signal entry
# --------------------------------------------------------------------------
@login_required(login_url="marketdata:login")
@require_http_methods(["GET"])
def manual_list(request):
    signals = ManualSignal.objects.select_related("instrument", "created_by")
    page = Paginator(signals, MANUAL_SIGNAL_PAGE_SIZE).get_page(request.GET.get("page"))
    return render(request, "strategies/manual_list.html", {"signals": page, "page": page})


@login_required(login_url="marketdata:login")
@require_http_methods(["GET", "POST"])
def manual_edit(request, pk=None):
    instance = get_object_or_404(ManualSignal, pk=pk) if pk else None
    form = ManualSignalForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        if obj.created_by_id is None:
            obj.created_by = request.user
        obj.save()
        messages.success(request, f"Saved manual signal for {obj.instrument.symbol} {obj.date}.")
        return redirect("strategies:manual_list")
    return render(request, "strategies/manual_form.html", {"form": form, "instance": instance})
