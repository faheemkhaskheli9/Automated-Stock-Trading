"""Thin orchestration layer shared by views, the management command and the
Celery task. Deferring the ``engine`` import (which pulls in scikit-learn via
``modeling``) keeps importing ``backtesting.services`` - and therefore
``backtesting.tasks`` at Celery autodiscovery - cheap.
"""

from __future__ import annotations


def run_backtest(backtest, *, created_by=None):
    """Run a backtest synchronously in the caller's process - the CLI command
    and tests use this. UI actions should use ``start_backtest_run`` instead
    so the request thread isn't blocked by a slow walk-forward sweep."""
    from .engine import run_backtest as _run

    return _run(backtest, created_by=created_by)


def start_backtest_run(backtest, *, created_by=None):
    """Create the ``BacktestRun`` row immediately (cheap - no fitting yet)
    and hand the actual walk-forward run to Celery.

    With ``CELERY_TASK_ALWAYS_EAGER`` (the local/test default - see
    ``settings/dev.py``) ``.delay()`` runs the task inline before returning,
    so the refreshed row already reflects the finished run; against a real
    worker it comes back ``running`` and the caller (the ``/backtests/``
    detail page) polls/refreshes to see it complete.
    """
    from .models import BacktestRun
    from .tasks import run_backtest_task

    run = BacktestRun.objects.create(backtest=backtest, created_by=created_by)
    run_backtest_task.delay(backtest.pk, run.pk)
    run.refresh_from_db()
    return run
