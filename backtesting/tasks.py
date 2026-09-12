"""Celery tasks for the backtesting app.

Unscheduled - like ``modeling.tasks``, wire a ``PeriodicTask`` (or trigger
ad hoc) once this runs somewhere Celery is deployed. Failures are recorded on
the ``BacktestRun`` row by ``engine.run_backtest`` itself, never raised.
"""

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task
def run_backtest_task(backtest_id: int, run_id: int | None = None) -> int | None:
    """Run every fold of ``Backtest(pk=backtest_id)``.

    ``run_id`` - when given (the async UI path via
    ``services.start_backtest_run``) - names a ``BacktestRun`` row already
    created by the caller; this task scores into that row instead of
    creating a new one. Omitted (the old synchronous CLI/task-only call
    shape), a new run is created here, same as before.
    """
    from .engine import run_backtest
    from .models import Backtest, BacktestRun

    backtest = Backtest.objects.filter(pk=backtest_id).first()
    if backtest is None:
        logger.warning("run_backtest_task: no Backtest %s", backtest_id)
        return None

    run = None
    if run_id is not None:
        run = BacktestRun.objects.filter(pk=run_id, backtest=backtest).first()
        if run is None:
            logger.warning(
                "run_backtest_task: no BacktestRun %s for backtest %s", run_id, backtest_id
            )
    return run_backtest(backtest, run=run).pk


@shared_task
def run_active_backtests() -> list[int]:
    from .models import Backtest
    from .services import run_backtest

    run_ids: list[int] = []
    for backtest in Backtest.objects.filter(is_active=True).select_related("model"):
        try:
            run_ids.append(run_backtest(backtest).pk)
        except Exception:  # noqa: BLE001 - isolate per backtest
            logger.exception("run_active_backtests failed for backtest=%s", backtest.pk)
    return run_ids
