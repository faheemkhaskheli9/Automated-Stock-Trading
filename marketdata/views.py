import csv
import logging
from datetime import timedelta
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.paginator import Paginator
from django.db.models import Count, Max, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
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
@require_GET
def instruments(request):
    """Searchable roster of saved PSX symbols with each one's latest stored
    daily close and how its most recent persisted model forecast turned out."""
    query = (request.GET.get("q") or "").strip()
    qs = (
        Instrument.objects.filter(exchange="PSX")
        .annotate(bar_count=Count("price_bars"))
        .order_by("symbol")
    )
    if query:
        qs = qs.filter(Q(symbol__icontains=query) | Q(name__icontains=query))
    page = Paginator(qs, 50).get_page(request.GET.get("page"))
    ids = [instrument.pk for instrument in page]

    # Latest stored daily bar per listed instrument (first row wins per id).
    last_bars: dict[int, PriceBar] = {}
    for bar in PriceBar.objects.filter(
        instrument_id__in=ids, timeframe=PriceBar.Timeframe.DAILY
    ).order_by("instrument_id", "-timestamp"):
        last_bars.setdefault(bar.instrument_id, bar)

    # Latest persisted model prediction per instrument (actual backfilled or not).
    predictions: dict[int, object] = {}
    if ids:
        from modeling.models import ModelPrediction

        for prediction in (
            ModelPrediction.objects.filter(instrument_id__in=ids)
            .select_related("model")
            .order_by("instrument_id", "-target_date", "-created_at")
        ):
            predictions.setdefault(prediction.instrument_id, prediction)

    rows = [
        {
            "instrument": instrument,
            "last_bar": last_bars.get(instrument.pk),
            "prediction": predictions.get(instrument.pk),
        }
        for instrument in page
    ]
    params = request.GET.copy()
    params.pop("page", None)
    return render(
        request,
        "marketdata/instruments.html",
        {
            "rows": rows,
            "page": page,
            "q": query,
            "query": params.urlencode(),
            "total": Instrument.objects.filter(exchange="PSX").count(),
        },
    )


# Indicator overlays the symbol-detail chart can draw over the candles. Only
# these periods are accepted from the query string - anything else is ignored
# rather than trusted straight into a rolling window.
OVERLAY_PERIODS = (10, 20, 50, 100, 200)
_SMA_COLORS = {10: "#d9822b", 20: "#0e9877", 50: "#2f6fce", 100: "#8b5cf6", 200: "#475569"}
_EMA_COLORS = {10: "#e0563f", 20: "#0aa27a", 50: "#3b82f6", 100: "#a855f7", 200: "#64748b"}

# Days-of-history choices for the detail chart; 0 means "everything stored".
DETAIL_RANGES = (90, 180, 365, 0)
_DEFAULT_RANGE = 180

_PX = (20.0, 980.0)  # chart x-extent inside the 1000-wide viewBox
_PY = (12.0, 250.0)  # price-area y-extent (top, bottom)
_VY = (266.0, 300.0)  # volume-strip y-extent (top, bottom)


def _sma(values, period):
    """Simple moving average, aligned to ``values`` (None until enough history)."""
    out = [None] * len(values)
    if period <= 0:
        return out
    run = 0.0
    for i, value in enumerate(values):
        run += value
        if i >= period:
            run -= values[i - period]
        if i >= period - 1:
            out[i] = run / period
    return out


def _ema(values, period):
    """Exponential moving average seeded with the first ``period``-bar SMA."""
    out = [None] * len(values)
    if period <= 0 or len(values) < period:
        return out
    prev = sum(values[:period]) / period
    out[period - 1] = prev
    k = 2.0 / (period + 1)
    for i in range(period, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def _polyline(series, window, lo, hi):
    """Space ``series`` (already sliced to the visible window) across the chart
    x-extent and map each value onto the price y-extent. Returns an SVG points
    string, skipping leading bars that don't have a value yet."""
    n = len(window)
    span = hi - lo or 1.0
    step = (_PX[1] - _PX[0]) / max(n - 1, 1)
    parts = []
    for i, value in enumerate(series):
        if value is None:
            continue
        x = _PX[0] + i * step
        y = _PY[1] - (value - lo) * (_PY[1] - _PY[0]) / span
        parts.append(f"{x:.2f},{y:.2f}")
    return " ".join(parts)


@login_required(login_url="marketdata:login")
@require_GET
def instrument_detail(request, symbol):
    """Candlestick + volume view for one saved PSX symbol, with optional
    moving-average overlays toggled through the query string
    (``?sma=20&sma=50&ema=20``) and a history-length selector (``?days=``)."""
    instrument = get_object_or_404(Instrument, exchange="PSX", symbol=symbol)

    try:
        days = int(request.GET.get("days", _DEFAULT_RANGE))
    except (TypeError, ValueError):
        days = _DEFAULT_RANGE
    if days not in DETAIL_RANGES:
        days = _DEFAULT_RANGE

    def _periods(name):
        picked = []
        for raw in request.GET.getlist(name):
            try:
                period = int(raw)
            except (TypeError, ValueError):
                continue
            if period in OVERLAY_PERIODS and period not in picked:
                picked.append(period)
        return sorted(picked)

    sma_periods = _periods("sma")
    ema_periods = _periods("ema")
    max_period = max([*sma_periods, *ema_periods, 0])

    all_bars = list(
        instrument.price_bars.filter(timeframe=PriceBar.Timeframe.DAILY).order_by("timestamp")
    )
    # Keep enough extra leading history that the longest overlay is already
    # "warm" at the left edge of the visible window.
    if days:
        window = all_bars[-days:]
        calc_bars = all_bars[-(days + max_period) :] if max_period else window
    else:
        window = calc_bars = all_bars
    offset = len(calc_bars) - len(window)

    closes = [float(bar.close) for bar in calc_bars]
    overlays = []
    for period in sma_periods:
        overlays.append(("sma", period, _SMA_COLORS[period], _sma(closes, period)[offset:]))
    for period in ema_periods:
        overlays.append(("ema", period, _EMA_COLORS[period], _ema(closes, period)[offset:]))

    candles = []
    latest = window[-1] if window else None
    chart = None
    if window:
        lows = [float(bar.low) for bar in window]
        highs = [float(bar.high) for bar in window]
        lo, hi = min(lows), max(highs)
        for _, _, _, series in overlays:
            vals = [v for v in series if v is not None]
            if vals:
                lo, hi = min(lo, *vals), max(hi, *vals)
        span = hi - lo or 1.0
        n = len(window)
        step = (_PX[1] - _PX[0]) / max(n - 1, 1)
        body_w = max(1.5, step * 0.6)
        max_vol = max((bar.volume for bar in window), default=0) or 1

        def price_y(value):
            return _PY[1] - (value - lo) * (_PY[1] - _PY[0]) / span

        for i, bar in enumerate(window):
            o, c = float(bar.open), float(bar.close)
            top, bottom = price_y(max(o, c)), price_y(min(o, c))
            vol_h = bar.volume / max_vol * (_VY[1] - _VY[0])
            x = _PX[0] + i * step
            candles.append(
                {
                    "x": x,
                    "body_x": x - body_w / 2,
                    "up": c >= o,
                    "wick_top": price_y(float(bar.high)),
                    "wick_bottom": price_y(float(bar.low)),
                    "body_y": top,
                    "body_h": max(bottom - top, 1.0),
                    "vol_y": _VY[1] - vol_h,
                    "vol_h": vol_h,
                }
            )
        chart = {
            "lo": lo,
            "hi": hi,
            "mid": (lo + hi) / 2,
            "body_w": body_w,
            "start": window[0].timestamp,
            "end": window[-1].timestamp,
        }

    overlay_lines = [
        {
            "key": f"{kind}{period}",
            "label": f"{kind.upper()} {period}",
            "color": color,
            "points": _polyline(series, window, chart["lo"], chart["hi"]),
        }
        for (kind, period, color, series) in overlays
        if window
    ]

    prediction = None if latest is None else _latest_prediction(instrument)
    forecast_predictors, selected_predictor, forecast_panel = _forecast_panel(
        request, instrument, latest
    )

    return render(
        request,
        "marketdata/instrument_detail.html",
        {
            "instrument": instrument,
            "candles": candles,
            "chart": chart,
            "overlay_lines": overlay_lines,
            "latest": latest,
            "bar_count": len(all_bars),
            "shown": len(window),
            "days": days,
            "ranges": DETAIL_RANGES,
            "overlay_periods": OVERLAY_PERIODS,
            "sma_periods": sma_periods,
            "ema_periods": ema_periods,
            "prediction": prediction,
            "forecast_predictors": forecast_predictors,
            "selected_predictor": selected_predictor,
            "forecast": forecast_panel,
            "research": _research_panels(instrument),
        },
    )


def _sentiment_tone(score):
    """Bucket a VADER compound score into a chip class (matches the usual
    ``|compound| >= 0.05`` neutral band)."""
    if score is None:
        return "unknown"
    if score >= 0.05:
        return "pos"
    if score <= -0.05:
        return "neg"
    return "neutral"


def _research_panels(instrument):
    """Point-in-time news / social / fundamentals context for the symbol
    detail page, read straight from the ``research`` app's raw tables.

    Each panel degrades on its own: news shows an empty state, while social
    and fundamentals render an explanatory "not configured" panel because
    their live ingestion is deferred (see ``research/providers/``)."""
    from research.models import CompanyFundamental, NewsItem, SocialMention
    from research.providers.news import news_features

    now = timezone.now()
    symbol, exchange = instrument.symbol, instrument.exchange

    headlines = list(
        NewsItem.objects.filter(exchange=exchange, symbol=symbol, published_at__lte=now).order_by(
            "-published_at"
        )[:12]
    )
    for item in headlines:
        item.tone = _sentiment_tone(item.sentiment)
    feats = news_features(symbol, now, exchange=exchange)
    news = {
        "headlines": headlines,
        "count_7d": int(feats.get("news.count_7d", 0)),
        "count_30d": int(feats.get("news.count_30d", 0)),
        "sentiment_mean_7d": feats.get("news.sentiment_mean_7d"),
        "sentiment_trend": feats.get("news.sentiment_trend"),
    }

    social_qs = SocialMention.objects.filter(exchange=exchange, symbol=symbol, posted_at__lte=now)
    social = {"count": social_qs.count(), "latest": social_qs.order_by("-posted_at").first()}

    report = (
        CompanyFundamental.objects.filter(
            exchange=exchange, symbol=symbol, as_of_report_date__lt=now.date()
        )
        .order_by("-as_of_report_date")
        .first()
    )
    fundamentals = None
    if report is not None:
        fundamentals = {
            "report_date": report.as_of_report_date,
            "source": report.source,
            "ratios": sorted(
                (name, value)
                for name, value in report.ratios.items()
                if isinstance(value, (int, float))
            ),
        }

    return {"news": news, "social": social, "fundamentals": fundamentals}


def _forecast_panel(request, instrument, latest):
    """Build the symbol-detail live-forecast panel: the list of selectable
    strict-path predictors, the chosen one (``?predictor=``, default
    ``naive``), and a rendered forecast for the session after the last bar."""
    from forecasting.registry import get_predictor_class, registered_keys

    keys = registered_keys()
    options = [
        {"key": key, "label": getattr(get_predictor_class(key), "display_name", "") or key}
        for key in keys
    ]
    selected = request.GET.get("predictor") or "naive"
    if selected not in keys:
        selected = "naive" if "naive" in keys else (keys[0] if keys else "")
    if latest is None or not selected:
        return options, selected, None

    from forecasting.services import latest_forecast

    result = latest_forecast(instrument.symbol, selected)
    panel = {
        "predictor_key": result.predictor_key,
        "display_name": result.display_name,
        "target_date": result.target_date,
        "error": result.error,
    }
    forecast = result.prediction
    if forecast is not None:
        last_close = float(latest.close)
        panel.update(
            {
                "predicted_close": forecast.predicted_close,
                "lower": forecast.lower,
                "upper": forecast.upper,
                "confidence_pct": (
                    None if forecast.confidence is None else forecast.confidence * 100
                ),
                "delta": forecast.predicted_close - last_close,
                "delta_pct": (
                    (forecast.predicted_close / last_close - 1) * 100 if last_close else None
                ),
            }
        )
    return options, selected, panel


def _latest_prediction(instrument):
    """Most recent persisted modeling forecast for this instrument, or None."""
    from modeling.models import ModelPrediction

    return (
        ModelPrediction.objects.filter(instrument=instrument)
        .select_related("model")
        .order_by("-target_date", "-created_at")
        .first()
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
