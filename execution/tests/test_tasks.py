from datetime import datetime, timezone
from decimal import Decimal

from django.test import TestCase

from marketdata.models import PriceBar
from portfolio.models import Position
from strategies.models import ManualSignal, Strategy

from ..models import Order
from ..tasks import run_trading_cycle
from .factories import make_account, make_instrument


def _add_bar(instrument, close, day):
    return PriceBar.objects.create(
        instrument=instrument,
        timestamp=datetime(2026, 1, day, tzinfo=timezone.utc),
        open=close,
        high=close,
        low=close,
        close=close,
        volume=1000,
    )


class RunTradingCycleTests(TestCase):
    def setUp(self):
        self.account = make_account(cash_balance=100_000)
        self.instrument = make_instrument()
        self.bar = _add_bar(self.instrument, close=Decimal("10"), day=1)
        self.strategy = Strategy.objects.create(
            name="Manual test strategy",
            key="manual",
            params={"instrument_id": self.instrument.id},
            account=self.account,
            is_active=True,
        )
        self.strategy.instruments.add(self.instrument)

    def test_ignores_inactive_strategies(self):
        self.strategy.is_active = False
        self.strategy.save()
        ManualSignal.objects.create(
            instrument=self.instrument, date=self.bar.timestamp.date(), action="buy"
        )

        order_ids = run_trading_cycle()

        self.assertEqual(order_ids, [])

    def test_ignores_strategies_without_an_account(self):
        self.strategy.account = None
        self.strategy.save()
        ManualSignal.objects.create(
            instrument=self.instrument, date=self.bar.timestamp.date(), action="buy"
        )

        order_ids = run_trading_cycle()

        self.assertEqual(order_ids, [])

    def test_hold_signal_places_no_order(self):
        # No ManualSignal entry for today -> ManualSignalStrategy holds.
        order_ids = run_trading_cycle()
        self.assertEqual(order_ids, [])

    def test_buy_signal_places_and_fills_an_order(self):
        ManualSignal.objects.create(
            instrument=self.instrument, date=self.bar.timestamp.date(), action="buy"
        )

        order_ids = run_trading_cycle()

        self.assertEqual(len(order_ids), 1)
        order = Order.objects.get(id=order_ids[0])
        self.assertEqual(order.status, Order.Status.FILLED)
        self.assertEqual(order.side, Order.Side.BUY)
        self.assertTrue(
            Position.objects.filter(account=self.account, instrument=self.instrument).exists()
        )

    def test_sell_signal_sells_the_full_existing_position(self):
        ManualSignal.objects.create(
            instrument=self.instrument, date=self.bar.timestamp.date(), action="buy"
        )
        run_trading_cycle()
        position = Position.objects.get(account=self.account, instrument=self.instrument)
        held_quantity = position.quantity

        day2 = _add_bar(self.instrument, close=Decimal("12"), day=2)
        ManualSignal.objects.create(
            instrument=self.instrument, date=day2.timestamp.date(), action="sell"
        )

        order_ids = run_trading_cycle()

        order = Order.objects.get(id=order_ids[-1])
        self.assertEqual(order.side, Order.Side.SELL)
        self.assertEqual(order.quantity, held_quantity)
        self.assertFalse(
            Position.objects.filter(account=self.account, instrument=self.instrument).exists()
        )

    def test_sell_signal_with_no_position_is_skipped(self):
        ManualSignal.objects.create(
            instrument=self.instrument, date=self.bar.timestamp.date(), action="sell"
        )
        order_ids = run_trading_cycle()
        self.assertEqual(order_ids, [])

    def test_one_broken_strategy_does_not_abort_the_cycle(self):
        good_instrument = make_instrument(symbol="LUCK")
        good_bar = _add_bar(good_instrument, close=Decimal("10"), day=1)
        good_strategy = Strategy.objects.create(
            name="Good",
            key="manual",
            params={"instrument_id": good_instrument.id},
            account=self.account,
            is_active=True,
        )
        good_strategy.instruments.add(good_instrument)
        ManualSignal.objects.create(
            instrument=good_instrument, date=good_bar.timestamp.date(), action="buy"
        )

        # Broken strategy: unregistered key slipped past validation (e.g. edited directly in DB).
        broken = Strategy.objects.create(
            name="Broken", key="does_not_exist", account=self.account, is_active=True
        )
        broken.instruments.add(self.instrument)

        order_ids = run_trading_cycle()

        self.assertEqual(len(order_ids), 1)
