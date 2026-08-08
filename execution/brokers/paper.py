"""Simulated broker: fills immediately against the latest stored PriceBar
(not a live network call - see marketdata.services for how bars get there),
updates Position/Account in the same DB. This is the only BrokerAdapter
implemented today - see base.py.
"""

from django.db import transaction
from django.utils import timezone

from portfolio.models import Account, Position

from ..models import Order, Trade
from .base import BrokerAdapter


class InsufficientFundsError(Exception):
    pass


class InsufficientPositionError(Exception):
    pass


class NoPriceDataError(Exception):
    pass


class PaperBroker(BrokerAdapter):
    def submit_order(self, order: Order) -> Order:
        order.status = Order.Status.SUBMITTED
        order.submitted_at = timezone.now()

        last_bar = order.instrument.price_bars.order_by("-timestamp").first()
        if last_bar is None:
            return self._reject(order, "no price data available for instrument")

        price = last_bar.close
        try:
            with transaction.atomic():
                if order.side == Order.Side.BUY:
                    self._fill_buy(order, price)
                else:
                    self._fill_sell(order, price)
        except InsufficientFundsError:
            return self._reject(order, "insufficient funds")
        except InsufficientPositionError:
            return self._reject(order, "insufficient position to sell")

        order.status = Order.Status.FILLED
        order.filled_quantity = order.quantity
        order.filled_price = price
        order.filled_at = timezone.now()
        order.save()
        Trade.objects.create(
            order=order, quantity=order.quantity, price=price, executed_at=order.filled_at
        )
        return order

    def cancel_order(self, order: Order) -> Order:
        if order.status in (Order.Status.PENDING, Order.Status.SUBMITTED):
            order.status = Order.Status.CANCELLED
            order.save()
        return order

    def get_positions(self, account: Account) -> list[Position]:
        return list(account.positions.select_related("instrument"))

    def get_account(self, account: Account) -> Account:
        return account

    def _fill_buy(self, order: Order, price):
        account = order.account
        cost = price * order.quantity
        account.refresh_from_db()
        if account.cash_balance < cost:
            raise InsufficientFundsError
        account.cash_balance -= cost
        account.save(update_fields=["cash_balance", "updated_at"])

        position, created = Position.objects.select_for_update().get_or_create(
            account=account,
            instrument=order.instrument,
            defaults={"quantity": order.quantity, "avg_entry_price": price},
        )
        if not created:
            total_cost = position.avg_entry_price * position.quantity + price * order.quantity
            position.quantity += order.quantity
            position.avg_entry_price = total_cost / position.quantity
            position.save(update_fields=["quantity", "avg_entry_price", "updated_at"])

    def _fill_sell(self, order: Order, price):
        account = order.account
        try:
            position = Position.objects.select_for_update().get(
                account=account, instrument=order.instrument
            )
        except Position.DoesNotExist:
            raise InsufficientPositionError from None

        if position.quantity < order.quantity:
            raise InsufficientPositionError

        proceeds = price * order.quantity
        account.refresh_from_db()
        account.cash_balance += proceeds
        account.save(update_fields=["cash_balance", "updated_at"])

        position.quantity -= order.quantity
        if position.quantity == 0:
            position.delete()
        else:
            position.save(update_fields=["quantity", "updated_at"])

    def _reject(self, order: Order, reason: str) -> Order:
        order.status = Order.Status.REJECTED
        order.rejection_reason = reason
        order.save()
        return order
