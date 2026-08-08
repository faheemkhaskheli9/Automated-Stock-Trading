"""Celery tasks for market data ingestion.

`sync_all_active_instruments` is meant to be scheduled via django-celery-beat
(configurable from the admin) for shortly after PSX market close, in
Asia/Karachi time (CELERY_TIMEZONE - see settings/base.py). Not wired into
a default schedule yet; add the periodic task via the admin/`PeriodicTask`
once this is deployed somewhere Celery actually runs.
"""

import logging

from celery import shared_task

from .services import sync_active_instruments

logger = logging.getLogger(__name__)


@shared_task
def sync_all_active_instruments() -> dict[str, int]:
    results = sync_active_instruments()
    logger.info("Market data sync complete: %s", results)
    return results
