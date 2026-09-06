"""Orchestration for the strict-path forecasting backtester.

``run_forecast_backtest`` is the single write path for
:class:`forecasting.models.ForecastBacktestRun`. It builds a run row from a
config, executes the ``forecasting.backtesting`` walk-forward, and freezes the
result on the row. It mirrors ``backtesting.engine.run_backtest`` /
``modeling.training.train_model``: **it never raises** - any failure lands on
the row as ``status="failed"`` + ``error``.

The heavy import (``forecasting.backtesting.engine`` pulls in the predictor
modules, which pull in scikit-learn / statsmodels) is deferred to call time so
importing this module - and therefore ``forecasting.tasks`` at Celery
autodiscovery - stays cheap.
"""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from django.utils import timezone

from .models import ForecastBacktestRun

logger = logging.getLogger(__name__)


def _as_aware(value, tz: ZoneInfo) -> datetime:
    """Coerce a date/datetime/ISO string to a tz-aware datetime in ``tz``."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=tz)
    if isinstance(value, str):
        return _as_aware(datetime.fromisoformat(value), tz)
    # a datetime.date
    return datetime(value.year, value.month, value.day, tzinfo=tz)


def _serialize(result) -> dict:
    """Flatten a ``WalkForwardResult`` into ``ForecastBacktestRun`` result fields."""
    folds = [
        {
            "index": f.index,
            "train_start": f.train_start.isoformat(),
            "train_end": f.train_end.isoformat(),
            "test_start": f.test_start.isoformat(),
            "test_end": f.test_end.isoformat(),
            "n_train": f.n_train,
            "n_test": f.n_test,
            "metrics": f.metrics,
        }
        for f in result.folds
    ]
    return {
        "n_folds": len(result.folds),
        "n_skipped_folds": len(result.skipped_folds),
        "n_predictions": len(result.predictions),
        "metrics": result.metrics,
        "naive_metrics": result.naive_metrics,
        "trading": result.trading,
        "equity_curve": result.trading.get("equity_curve", []),
        "folds": folds,
        "predictions": result.predictions,
        "skipped_folds": result.skipped_folds,
    }


def run_forecast_backtest(
    *,
    predictor_key: str,
    symbol: str,
    start,
    end,
    params: dict | None = None,
    exchange: str = "PSX",
    exchange_timezone: str = "Asia/Karachi",
    provider_keys=None,
    scheme: str = ForecastBacktestRun.Scheme.EXPANDING,
    train_span: int = 250,
    test_span: int = 21,
    step: int = 21,
    gap: int = 1,
    allow_short: bool = False,
    long_threshold: float = 0.0,
    cost_bps: float = 0.0,
    initial_cash: float = 100_000.0,
    name: str = "",
    created_by=None,
) -> ForecastBacktestRun:
    """Run a strict-path walk-forward and persist it. Never raises."""
    from .backtesting.engine import looks_leaky, walk_forward
    from .features import DEFAULT_PROVIDERS

    tz = ZoneInfo(exchange_timezone)
    start_dt = _as_aware(start, tz)
    end_dt = _as_aware(end, tz)
    providers = list(DEFAULT_PROVIDERS) if provider_keys is None else list(provider_keys)

    run = ForecastBacktestRun(
        name=name,
        predictor_key=predictor_key,
        params=dict(params or {}),
        symbol=symbol,
        exchange=exchange,
        exchange_timezone=exchange_timezone,
        provider_keys=providers,
        scheme=scheme,
        train_span=train_span,
        test_span=test_span,
        step=step,
        gap=gap,
        start=start_dt.date(),
        end=end_dt.date(),
        allow_short=allow_short,
        long_threshold=long_threshold,
        cost_bps=cost_bps,
        initial_cash=initial_cash,
        created_by=created_by,
    )
    run.save()

    try:
        result = walk_forward(
            predictor_key,
            symbol,
            start_dt,
            end_dt,
            params=run.params,
            scheme=scheme,
            train_span=train_span,
            test_span=test_span,
            step=step,
            gap=gap,
            provider_keys=providers,
            exchange=exchange,
            exchange_timezone=exchange_timezone,
            allow_short=allow_short,
            long_threshold=long_threshold,
            cost_bps=cost_bps,
            initial_cash=initial_cash,
        )
    except Exception as exc:  # noqa: BLE001 - recorded on the run, never propagated
        logger.exception("Forecast backtest failed for %s %s", predictor_key, symbol)
        run.status = ForecastBacktestRun.Status.FAILED
        run.error = f"{type(exc).__name__}: {exc}"
        run.finished_at = timezone.now()
        run.save()
        return run

    for field, value in _serialize(result).items():
        setattr(run, field, value)
    run.looks_leaky = looks_leaky(result)
    run.status = ForecastBacktestRun.Status.SUCCESS
    run.finished_at = timezone.now()
    run.save()
    return run
