"""Celery task for the modelsearch app.

Unscheduled - like ``modeling.tasks``. Wire a ``PeriodicTask`` (or trigger it
ad hoc) once this runs somewhere Celery is deployed.
"""

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task
def run_model_search_task(search_id: int) -> int | None:
    from .models import ModelSearch
    from .services import run_search

    search = ModelSearch.objects.filter(pk=search_id).first()
    if search is None:
        logger.warning("run_model_search_task: no ModelSearch %s", search_id)
        return None
    return run_search(search).pk
