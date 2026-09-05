"""Thin orchestration layer shared by views, the management command and the
Celery task. Deferring the ``engine`` import (which pulls in scikit-learn via
``modeling``) keeps importing ``backtesting.services`` - and therefore
``backtesting.tasks`` at Celery autodiscovery - cheap.
"""

from __future__ import annotations


def run_backtest(backtest, *, created_by=None):
    from .engine import run_backtest as _run

    return _run(backtest, created_by=created_by)
