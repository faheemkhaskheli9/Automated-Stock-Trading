import csv
import logging
from datetime import timedelta
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.paginator import Paginator
from django.db.models import Count, Max
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .forms import HistoryForm
from .models import Instrument, PriceBar
from .services import sync_instrument_history

logger = logging.getLogger(__name__)


@login_required(login_url="marketdata:login")
@require_GET
def dashboard(request):
    instruments = Instrument.objects.filter(exchange="PSX").annotate(
        bar_count=Count("price_bars"), latest_date=Max("price_bars__timestamp")
    )
    initial = {"symbol": request.GET.get("symbol", ""), "start": "", "end": ""}
    if not initial["symbol"]:
        initial["symbol"] = instruments.values_list("symbol", flat=True).first() or ""
    params = {**initial, **request.GET.dict()}
    form = HistoryForm(params) if params["symbol"] else HistoryForm()
    bars = PriceBar.objects.none()
    selected = None
    if form.is_bound and form.is_valid():
        selected = instruments.filter(symbol=form.cleaned_data["symbol"]).first()
        if selected:
            bars = selected.price_bars.filter(timeframe=PriceBar.Timeframe.DAILY)
            if form.cleaned_data["start"]:
                bars = bars.filter(timestamp__date__gte=form.cleaned_data["start"])
            if form.cleaned_data["end"]:
                bars = bars.filter(timestamp__date__lte=form.cleaned_data["end"])
    bars = bars.order_by("-timestamp")
    if request.GET.get("export") == "csv" and selected:
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{selected.symbol}-history.csv"'
        writer = csv.writer(response)
        writer.writerow(["date", "open", "high", "low", "close", "volume", "is_anomaly"])
        for bar in bars.iterator():
            writer.writerow(
                [
                    timezone.localtime(bar.timestamp).date(),
                    bar.open,
                    bar.high,
                    bar.low,
                    bar.close,
                    bar.volume,
                    bar.is_anomaly,
                ]
            )
        return response
    latest = bars.first()
    chart_bars = list(bars[:365])[::-1]
    points = ""
    chart_low = chart_high = None
    if chart_bars:
        prices = [float(bar.close) for bar in chart_bars]
        chart_low, chart_high = min(prices), max(prices)
        spread = chart_high - chart_low or 1
        points = " ".join(
            f"{20 + i * 960 / max(len(prices) - 1, 1):.2f},{200 - (price - chart_low) * 170 / spread:.2f}"
            for i, price in enumerate(prices)
        )
    query = request.GET.copy()
    query.pop("page", None)
    query.pop("export", None)
    query["symbol"] = params["symbol"]
    return render(
        request,
        "marketdata/dashboard.html",
        {
            "form": form,
            "instruments": instruments,
            "selected": selected,
            "page": Paginator(bars, 50).get_page(request.GET.get("page")),
            "latest": latest,
            "points": points,
            "chart_low": chart_low,
            "chart_high": chart_high,
            "chart_bars": chart_bars,
            "query": query.urlencode(),
            "total_bars": PriceBar.objects.filter(instrument__exchange="PSX").count(),
        },
    )


@login_required(login_url="marketdata:login")
@permission_required("marketdata.add_pricebar", raise_exception=True)
@require_POST
def sync_history(request):
    form = HistoryForm(request.POST)
    if not form.is_valid():
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
        return redirect("marketdata:dashboard")
    data = form.cleaned_data
    end = data["end"] or timezone.localdate()
    start = data["start"] or end - timedelta(days=365)
    instrument, _ = Instrument.objects.get_or_create(symbol=data["symbol"], exchange="PSX")
    try:
        count = sync_instrument_history(instrument, start=start, end=end)
    except Exception:
        logger.exception("Dashboard sync failed for %s", instrument.symbol)
        messages.error(
            request,
            "Could not fetch PSX data. Your saved history is still available. Try again later.",
        )
    else:
        if count:
            messages.success(
                request,
                f"Saved {count:,} daily bars for {instrument.symbol}. Existing dates were updated without duplicates.",
            )
        else:
            messages.warning(
                request,
                "No data returned. Check the symbol and dates, or retry later. Existing history was kept.",
            )
    return redirect(
        reverse("marketdata:dashboard") + "?" + urlencode({"symbol": instrument.symbol})
    )
