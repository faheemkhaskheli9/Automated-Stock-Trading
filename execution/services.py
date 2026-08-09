"""Order placement: the one path from "a strategy/operator wants to trade"
to a filled/rejected Order. Always goes through risk.engine.evaluate before
ever reaching a broker.
"""

from datetime import timedelta

from django.utils import timezone

from marketdata.models import Instrument
from portfolio.models import Account
from risk.engine import evaluate
from strategies.models import Strategy
from strategies.signals import Action

from .brokers import get_broker
from .models import Order
from .notifications import send_alert

# How recently an identical (account, instrument, side) order must have
# been placed to be treated as a likely duplicate (e.g. a stuck scheduler
# re-running the same cycle) rather than a genuine new decision.
DUPLICATE_ORDER_WINDOW = timedelta(minutes=5)


def place_order(
    account: Account,
    instrument: Instrument,
    side: Action,
    quantity: int,
    strategy: Strategy | None = None,
) -> Order:
    order = _place_order(account, instrument, side, quantity, strategy)
    _notify(order)
    return order


def _place_order(
    account: Account,
    instrument: Instrument,
    side: Action,
    quantity: int,
    strategy: Strategy | None,
) -> Order:
    if side == Action.HOLD:
        raise ValueError("Cannot place an order for a HOLD action")

    if _is_duplicate(account, instrument, side):
        return Order.objects.create(
            account=account,
            instrument=instrument,
            strategy=strategy,
            side=side.value,
            quantity=quantity,
            status=Order.Status.REJECTED,
            rejection_reason="duplicate order guard: a matching order was placed recently",
        )

    last_bar = instrument.price_bars.order_by("-timestamp").first()
    order = Order.objects.create(
        account=account,
        instrument=instrument,
        strategy=strategy,
        side=side.value,
        quantity=quantity,
    )

    if last_bar is None:
        return _reject(order, "no price data available for risk evaluation")

    result = evaluate(account, instrument, side, quantity, last_bar.close, strategy=strategy)
    if not result.approved:
        return _reject(order, result.reason)

    return get_broker(account).submit_order(order)


def _notify(order: Order) -> None:
    label = f"{order.side} {order.quantity} {order.instrument.symbol} ({order.account})"
    if order.status == Order.Status.FILLED:
        send_alert(
            f"Order filled: {order.instrument.symbol}",
            f"{label} filled at {order.filled_price}.",
        )
    elif order.status == Order.Status.REJECTED:
        send_alert(
            f"Order rejected: {order.instrument.symbol}",
            f"{label} rejected: {order.rejection_reason}",
        )


def _is_duplicate(account: Account, instrument: Instrument, side: Action) -> bool:
    cutoff = timezone.now() - DUPLICATE_ORDER_WINDOW
    return (
        Order.objects.filter(
            account=account, instrument=instrument, side=side.value, created_at__gte=cutoff
        )
        .exclude(status__in=[Order.Status.REJECTED, Order.Status.CANCELLED])
        .exists()
    )


def _reject(order: Order, reason: str) -> Order:
    order.status = Order.Status.REJECTED
    order.rejection_reason = reason
    order.save()
    return order
