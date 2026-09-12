"""Celery task for the modelsearch app.

Unscheduled - like ``modeling.tasks``. Wire a ``PeriodicTask`` (or trigger it
ad hoc) once this runs somewhere Celery is deployed.
"""

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task
def run_model_search_task(search_id: int, run_id: int | None = None) -> int | None:
    """Evaluate every candidate in ``ModelSearch(pk=search_id)``.

    ``run_id`` - when given (the async UI path via
    ``services.start_search_run``) - names a ``ModelSearchRun`` row already
    created by the caller; this task scores into that row instead of
    creating a new one. Omitted (the old synchronous CLI/task-only call
    shape), a new run is created here, same as before.
    """
    from .models import ModelSearch, ModelSearchRun
    from .search import run_search

    search = ModelSearch.objects.filter(pk=search_id).first()
    if search is None:
        logger.warning("run_model_search_task: no ModelSearch %s", search_id)
        return None

    run = None
    if run_id is not None:
        run = ModelSearchRun.objects.filter(pk=run_id, search=search).first()
        if run is None:
            logger.warning(
                "run_model_search_task: no ModelSearchRun %s for search %s", run_id, search_id
            )
    return run_search(search, run=run).pk
