from datetime import datetime, timezone
from decimal import Decimal

from django.test import TestCase

from marketdata.models import PriceBar
from portfolio.models import Position

from ..brokers.paper import PaperBroker
from ..models import Order
from .factories import make_account, make_instrument, make_order


def _add_bar(instrument, close, day=1):
    return PriceBar.objects.create(
        instrument=instrument,
        timestamp=datetime(2026, 1, day, tzinfo=timezone.utc),
        open=close,
        high=close,
        low=close,
        close=close,
        volume=1000,
    )


class PaperBrokerBuyTests(TestCase):
    def setUp(self):
        self.broker = PaperBroker()
        self.account = make_account(cash_balance=1000)
        self.instrument = make_instrument()

    def test_fills_buy_and_deducts_cash(self):
        _add_bar(self.instrument, close=Decimal("10"))
        order = make_order(self.account, self.instrument, side=Order.Side.BUY, quantity=50)

        result = self.broker.submit_order(order)

        self.assertEqual(result.status, Order.Status.FILLED)
        self.assertEqual(result.filled_price, Decimal("10"))
        self.account.refresh_from_db()
        self.assertEqual(self.account.cash_balance, Decimal("500"))  # 1000 - 50*10
        position = Position.objects.get(account=self.account, instrument=self.instrument)
        self.assertEqual(position.quantity, 50)
        self.assertEqual(position.avg_entry_price, Decimal("10"))

    def test_second_buy_averages_entry_price(self):
        _add_bar(self.instrument, close=Decimal("10"))
        self.broker.submit_order(make_order(self.account, self.instrument, quantity=50))

        _add_bar(self.instrument, close=Decimal("20"), day=2)
        self.account.cash_balance = Decimal("1000")  # top up for the second buy
        self.account.save()
        self.broker.submit_order(make_order(self.account, self.instrument, quantity=50))

        position = Position.objects.get(account=self.account, instrument=self.instrument)
        self.assertEqual(position.quantity, 100)
        self.assertEqual(position.avg_entry_price, Decimal("15"))  # (50*10 + 50*20) / 100

    def test_rejects_when_insufficient_funds(self):
        _add_bar(self.instrument, close=Decimal("100"))
        order = make_order(self.account, self.instrument, side=Order.Side.BUY, quantity=1000)

        result = self.broker.submit_order(order)

        self.assertEqual(result.status, Order.Status.REJECTED)
        self.assertIn("insufficient funds", result.rejection_reason)
        self.account.refresh_from_db()
        self.assertEqual(self.account.cash_balance, Decimal("1000"))  # untouched

    def test_rejects_when_no_price_data(self):
        order = make_order(self.account, self.instrument, quantity=10)
        result = self.broker.submit_order(order)
        self.assertEqual(result.status, Order.Status.REJECTED)
        self.assertIn("no price data", result.rejection_reason)


class PaperBrokerSellTests(TestCase):
    def setUp(self):
        self.broker = PaperBroker()
        self.account = make_account(cash_balance=0)
        self.instrument = make_instrument()
        Position.objects.create(
            account=self.account,
            instrument=self.instrument,
            quantity=50,
            avg_entry_price=Decimal("10"),
        )

    def test_fills_sell_and_credits_cash(self):
        _add_bar(self.instrument, close=Decimal("15"))
        order = make_order(self.account, self.instrument, side=Order.Side.SELL, quantity=50)

        result = self.broker.submit_order(order)

        self.assertEqual(result.status, Order.Status.FILLED)
        self.account.refresh_from_db()
        self.assertEqual(self.account.cash_balance, Decimal("750"))  # 50*15
        self.assertFalse(
            Position.objects.filter(account=self.account, instrument=self.instrument).exists()
        )

    def test_partial_sell_reduces_position(self):
        _add_bar(self.instrument, close=Decimal("15"))
        self.broker.submit_order(
            make_order(self.account, self.instrument, side=Order.Side.SELL, quantity=20)
        )

        position = Position.objects.get(account=self.account, instrument=self.instrument)
        self.assertEqual(position.quantity, 30)

    def test_rejects_when_insufficient_position(self):
        _add_bar(self.instrument, close=Decimal("15"))
        order = make_order(self.account, self.instrument, side=Order.Side.SELL, quantity=999)

        result = self.broker.submit_order(order)

        self.assertEqual(result.status, Order.Status.REJECTED)
        self.assertIn("insufficient position", result.rejection_reason)

    def test_rejects_selling_with_no_position_at_all(self):
        other_instrument = make_instrument(symbol="LUCK")
        _add_bar(other_instrument, close=Decimal("15"))
        order = make_order(self.account, other_instrument, side=Order.Side.SELL, quantity=1)

        result = self.broker.submit_order(order)
        self.assertEqual(result.status, Order.Status.REJECTED)


class PaperBrokerCancelTests(TestCase):
    def test_cancels_pending_order(self):
        account = make_account()
        instrument = make_instrument()
        order = make_order(account, instrument)

        result = PaperBroker().cancel_order(order)

        self.assertEqual(result.status, Order.Status.CANCELLED)

    def test_does_not_cancel_filled_order(self):
        account = make_account()
        instrument = make_instrument()
        order = make_order(account, instrument, status=Order.Status.FILLED)

        result = PaperBroker().cancel_order(order)

        self.assertEqual(result.status, Order.Status.FILLED)
