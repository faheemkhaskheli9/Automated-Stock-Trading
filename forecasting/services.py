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
from dataclasses import dataclass
from datetime import datetime, time, timedelta
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


@dataclass
class LiveForecast:
    """Best-effort next-session forecast for the symbol-detail panel.

    ``prediction`` is a :class:`forecasting.base.PricePrediction` on success;
    on any failure it is ``None`` and ``error`` carries a short reason. The
    producing helper never raises.
    """

    predictor_key: str
    display_name: str
    target_date: "object | None" = None
    prediction: "object | None" = None
    error: "str | None" = None


def latest_forecast(
    symbol: str,
    predictor_key: str = "naive",
    *,
    exchange: str = "PSX",
    exchange_timezone: str = "Asia/Karachi",
    provider_keys: tuple[str, ...] = ("technical",),
) -> LiveForecast:
    """Forecast the close of the session following the last stored daily bar.

    Fits the chosen predictor (if trainable) on every stored bar known before
    the day after the last saved session, then forecasts the next weekday.
    Only price + ``technical`` features are used - the news/fundamentals/social
    providers are stubs and would only make a dashboard panel slow and fragile.
    This is a convenience estimate, not the leakage-strict operational path:
    it picks the next weekday rather than consulting an exchange calendar.

    Never raises: any failure is returned as :attr:`LiveForecast.error`.
    """
    from marketdata.models import PriceBar

    from .registry import get_predictor_class

    zone = ZoneInfo(exchange_timezone)
    try:
        cls = get_predictor_class(predictor_key)
    except KeyError as exc:
        return LiveForecast(predictor_key, predictor_key, error=str(exc))
    display_name = getattr(cls, "display_name", "") or predictor_key
    target_date = None

    try:
        last_ts = (
            PriceBar.objects.filter(
                instrument__symbol=symbol,
                instrument__exchange=exchange,
                timeframe=PriceBar.Timeframe.DAILY,
            )
            .order_by("-timestamp")
            .values_list("timestamp", flat=True)
            .first()
        )
        if last_ts is None:
            return LiveForecast(
                predictor_key, display_name, error="No saved history to forecast from."
            )

        last_session = last_ts.astimezone(zone).date()
        as_of = datetime.combine(last_session + timedelta(days=1), time.min, zone)
        target_date = last_session + timedelta(days=1)
        while target_date.weekday() >= 5 or target_date <= last_session:
            target_date += timedelta(days=1)

        from .features import assemble_prediction_frame, assemble_training_frame

        predictor = cls()
        if getattr(cls, "trainable", False):
            predictor.fit(
                assemble_training_frame(
                    symbol,
                    datetime(1900, 1, 1, tzinfo=zone),
                    as_of,
                    exchange=exchange,
                    exchange_timezone=exchange_timezone,
                    provider_keys=provider_keys,
                )
            )
        frame = assemble_prediction_frame(
            symbol,
            as_of,
            target_date=target_date,
            exchange=exchange,
            exchange_timezone=exchange_timezone,
            provider_keys=provider_keys,
        )
        results = predictor.predict_series(frame)
    except Exception as exc:  # noqa: BLE001 - surfaced on the panel, never propagated
        logger.debug("latest_forecast failed for %s/%s", symbol, predictor_key, exc_info=True)
        return LiveForecast(
            predictor_key,
            display_name,
            target_date=target_date,
            error=f"{type(exc).__name__}: {exc}",
        )

    if not results:
        return LiveForecast(
            predictor_key,
            display_name,
            target_date=target_date,
            error="Predictor returned nothing.",
        )
    return LiveForecast(predictor_key, display_name, target_date=target_date, prediction=results[0])
