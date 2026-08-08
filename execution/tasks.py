"""The live/paper trading cycle: for each active Strategy with an Account
attached, generate a signal per instrument and place an order for it.

Not yet wired to a beat schedule - add a PeriodicTask (django-celery-beat,
via admin) during PSX market hours (Asia/Karachi - see CELERY_TIMEZONE in
settings/base.py) once this runs somewhere Celery is actually deployed.
"""

import logging

from celery import shared_task

from marketdata.models import PriceBar
from marketdata.providers.base import Bar
from portfolio.models import Position
from strategies.models import Strategy
from strategies.signals import Action

from .services import place_order

logger = logging.getLogger(__name__)

# Fallback order size (shares) when a Strategy's params don't specify one.
# Real position sizing is intentionally out of scope for v1 - risk.engine's
# max-position-size check is what actually bounds exposure; this is just a
# starting lot size for that check to accept or reject.
DEFAULT_ORDER_QUANTITY = 100


@shared_task
def run_trading_cycle() -> list[int]:
    """Returns the ids of every Order placed this cycle (including rejected
    ones - rejection is a valid, logged outcome, not a failure)."""
    order_ids = []
    for strategy_model in Strategy.objects.filter(
        is_active=True, account__isnull=False
    ).select_related("account"):
        try:
            strategy = strategy_model.build()
        except Exception:
            logger.exception("Failed to build strategy %s", strategy_model)
            continue

        for instrument in strategy_model.instruments.all():
            try:
                order = _run_one(strategy_model, strategy, instrument)
            except Exception:
                logger.exception(
                    "Trading cycle failed for strategy=%s instrument=%s", strategy_model, instrument
                )
                continue
            if order is not None:
                order_ids.append(order.id)

    return order_ids


def _run_one(strategy_model: Strategy, strategy, instrument):
    bars = _load_bars(instrument)
    if not bars:
        return None

    signals = strategy.generate_signals(bars)
    if not signals:
        return None

    last_signal = signals[-1]
    if last_signal.action == Action.HOLD:
        return None

    quantity = _determine_quantity(strategy_model, instrument, last_signal.action)
    if quantity <= 0:
        return None

    return place_order(
        strategy_model.account, instrument, last_signal.action, quantity, strategy=strategy_model
    )


def _load_bars(instrument) -> list[Bar]:
    rows = PriceBar.objects.filter(
        instrument=instrument, timeframe=PriceBar.Timeframe.DAILY
    ).order_by("timestamp")
    return [
        Bar(
            timestamp=row.timestamp,
            open=float(row.open),
            high=float(row.high),
            low=float(row.low),
            close=float(row.close),
            volume=row.volume,
            is_anomaly=row.is_anomaly,
        )
        for row in rows
    ]


def _determine_quantity(strategy_model: Strategy, instrument, action: Action) -> int:
    if action == Action.SELL:
        position = Position.objects.filter(
            account=strategy_model.account, instrument=instrument
        ).first()
        return position.quantity if position else 0
    return int(strategy_model.params.get("order_quantity", DEFAULT_ORDER_QUANTITY))
