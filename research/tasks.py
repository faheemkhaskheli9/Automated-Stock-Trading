"""Celery tasks for research/feature ingestion.

Same scheduling story as `marketdata.tasks`: not wired to a beat schedule
here. Add a `PeriodicTask` (django-celery-beat, via admin) for shortly
after PSX close once deployed somewhere Celery runs - see
`docs/DEPLOYMENT.md`.
"""

import logging
from datetime import timezone as _tz

from celery import shared_task
from django.utils import timezone

from marketdata.models import Instrument

from .providers.news import ingest_feeds
from .services import get_or_build_snapshot

logger = logging.getLogger(__name__)


@shared_task
def ingest_news(exchange: str = "PSX") -> int:
    created = ingest_feeds(exchange=exchange)
    logger.info("research.ingest_news(%s): %s new NewsItem(s)", exchange, created)
    return created


@shared_task
def sync_all_research(exchange: str = "PSX") -> dict[str, int]:
    """Ingest news, then build today's `ResearchSnapshot` for every active
    instrument. One symbol failing doesn't abort the rest."""
    ingest_news(exchange=exchange)
    as_of = timezone.now().astimezone(_tz.utc)
    results: dict[str, int] = {}
    for symbol in Instrument.objects.filter(exchange=exchange, is_active=True).values_list(
        "symbol", flat=True
    ):
        try:
            snap = get_or_build_snapshot(symbol, as_of, exchange=exchange, rebuild=True)
            results[symbol] = len(snap.features)
        except Exception:
            logger.exception("sync_all_research: failed for %s", symbol)
            results[symbol] = 0
    logger.info("research snapshot sync complete: %s", results)
    return results
