"""Operator UI for the research layer (Phase 9 U3).

Read views over the raw signal tables + the frozen `ResearchSnapshot`
cache, plus a synchronous "build a snapshot now" action and manual
fundamentals entry. Django admin stays as the power-user fallback.
"""

from __future__ import annotations

import logging
from datetime import datetime, time
from datetime import timezone as py_timezone

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from marketdata.models import Instrument

from .forms import FundamentalForm, SyncForm
from .models import CompanyFundamental, NewsItem, ResearchSnapshot
from .providers.news import ingest_feeds
from .services import get_or_build_snapshot

logger = logging.getLogger(__name__)


def _as_of_datetime(day):
    if day is None:
        return timezone.now()
    return datetime.combine(day, time.min, tzinfo=py_timezone.utc)


@login_required(login_url="marketdata:login")
@require_http_methods(["GET"])
def index(request):
    snapshots = ResearchSnapshot.objects.order_by("-as_of", "symbol")[:50]
    headlines = NewsItem.objects.order_by("-published_at")[:20]
    fundamentals = CompanyFundamental.objects.order_by("symbol", "-as_of_report_date")[:50]
    return render(
        request,
        "research/index.html",
        {
            "snapshots": snapshots,
            "headlines": headlines,
            "fundamentals": fundamentals,
            "form": SyncForm(initial={"exchange": "PSX"}),
            "news_total": NewsItem.objects.count(),
            "snapshot_total": ResearchSnapshot.objects.count(),
        },
    )


@login_required(login_url="marketdata:login")
@require_http_methods(["GET"])
def symbol_detail(request, symbol=None):
    symbol = (request.GET.get("symbol") or symbol or "").strip().upper()
    if not symbol:
        messages.error(request, "Pick a symbol.")
        return redirect("research:index")
    instrument = Instrument.objects.filter(symbol=symbol).first()
    if instrument is None:
        messages.error(request, f"No instrument {symbol!r}.")
        return redirect("research:index")

    from marketdata.views import _research_panels

    panels = _research_panels(instrument)
    snapshot = (
        ResearchSnapshot.objects.filter(exchange=instrument.exchange, symbol=symbol)
        .order_by("-as_of")
        .first()
    )
    features = sorted(snapshot.features.items()) if snapshot else []
    return render(
        request,
        "research/symbol_detail.html",
        {
            "instrument": instrument,
            "symbol": symbol,
            "news": panels["news"],
            "social": panels["social"],
            "fundamentals": panels["fundamentals"],
            "snapshot": snapshot,
            "features": features,
            "form": SyncForm(initial={"symbol": symbol, "exchange": instrument.exchange}),
        },
    )


@login_required(login_url="marketdata:login")
@require_http_methods(["POST"])
def sync(request):
    form = SyncForm(request.POST)
    if not form.is_valid():
        for errs in form.errors.values():
            for e in errs:
                messages.error(request, e)
        return redirect("research:index")

    data = form.cleaned_data
    symbol, exchange = data["symbol"], data["exchange"]
    as_of = _as_of_datetime(data["as_of"])
    try:
        if data["ingest_news"]:
            created = ingest_feeds(exchange=exchange)
            messages.info(request, f"News ingest: {created} new item(s).")
        snap = get_or_build_snapshot(symbol, as_of, exchange=exchange, rebuild=True)
        messages.success(
            request,
            f"Built snapshot for {symbol} @ {as_of:%Y-%m-%d}: {len(snap.features)} feature(s).",
        )
    except Exception as exc:  # noqa: BLE001 - surfaced to the operator
        logger.exception("research sync failed for %s", symbol)
        messages.error(request, f"Sync failed: {exc}")
    return redirect(f"{_symbol_url()}?symbol={symbol}")


def _symbol_url():
    from django.urls import reverse

    return reverse("research:symbol_detail")


@login_required(login_url="marketdata:login")
@require_http_methods(["GET", "POST"])
def fundamental_edit(request, pk=None):
    instance = get_object_or_404(CompanyFundamental, pk=pk) if pk else None
    form = FundamentalForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        obj = form.save()
        messages.success(request, f"Saved fundamentals for {obj.symbol} @ {obj.as_of_report_date}.")
        return redirect("research:index")
    return render(request, "research/fundamental_form.html", {"form": form, "instance": instance})
