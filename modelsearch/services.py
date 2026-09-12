"""Thin orchestration layer shared by views, the management command and the
Celery task. Heavy imports (scikit-learn, ``modeling.training``) stay inside the
functions so importing ``modelsearch.services`` - and ``modelsearch.tasks`` at
Celery autodiscovery - stays cheap.
"""

from __future__ import annotations


def run_search(search, *, created_by=None):
    """Run a search synchronously in the caller's process - the CLI command
    and tests use this. UI actions should use ``start_search_run`` instead
    so the request thread isn't blocked by a slow sweep."""
    from .search import run_search as _run

    return _run(search, created_by=created_by)


def start_search_run(search, *, created_by=None):
    """Create the ``ModelSearchRun`` row immediately (cheap - no fitting yet)
    and hand the actual sweep to Celery.

    With ``CELERY_TASK_ALWAYS_EAGER`` (the local/test default - see
    ``settings/dev.py``) ``.delay()`` runs the task inline before returning,
    so the refreshed row already reflects the finished run; against a real
    worker it comes back ``running`` and the caller (the ``/model-search/``
    detail page) polls/refreshes to see it complete.
    """
    from .models import ModelSearchRun
    from .tasks import run_model_search_task

    run = ModelSearchRun.objects.create(search=search, created_by=created_by)
    run_model_search_task.delay(search.pk, run.pk)
    run.refresh_from_db()
    return run


def promote_result(result, *, name=None, activate=False):
    """Create a new ``modeling.TradingModel`` from a winning candidate.

    Copies the search's feature/target spec, instruments and train window;
    takes the estimator key + params from ``result``. Does **not** train it -
    the operator does that from the normal ``/modeling/`` detail page.
    """
    from modeling.models import TradingModel

    search = result.search
    model = TradingModel(
        name=name or f"{search.name} · {result.estimator_key}",
        estimator_key=result.estimator_key,
        estimator_params=result.estimator_params or {},
        feature_spec=search.feature_spec,
        target_spec=search.target_spec,
        train_start=search.train_start,
        train_end=search.train_end,
        holdout_fraction=search.holdout_fraction,
        is_active=activate,
    )
    model.full_clean(exclude=["instruments"])
    model.save()
    model.instruments.set(search.instruments.all())
    return model
