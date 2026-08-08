from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

from marketdata.models import PriceBar

from ..models import Order
from ..services import place_order
from .factories import make_account, make_instrument


def _add_bar(instrument, close=Decimal("10")):
    return PriceBar.objects.create(
        instrument=instrument,
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        open=close,
        high=close,
        low=close,
        close=close,
        volume=1000,
    )


class PlaceOrderTests(TestCase):
    def setUp(self):
        self.account = make_account(cash_balance=100_000)
        self.instrument = make_instrument()

    def test_hold_action_raises(self):
        from strategies.signals import Action

        with self.assertRaises(ValueError):
            place_order(self.account, self.instrument, Action.HOLD, 10)

    def test_no_price_data_rejects_without_creating_a_trade(self):
        from strategies.signals import Action

        order = place_order(self.account, self.instrument, Action.BUY, 10)

        self.assertEqual(order.status, Order.Status.REJECTED)
        self.assertIn("no price data", order.rejection_reason)
        self.assertEqual(order.trades.count(), 0)

    def test_successful_buy_reaches_the_broker_and_fills(self):
        from strategies.signals import Action

        _add_bar(self.instrument)
        order = place_order(self.account, self.instrument, Action.BUY, 10)

        self.assertEqual(order.status, Order.Status.FILLED)
        self.assertEqual(order.trades.count(), 1)

    def test_duplicate_order_is_rejected_before_touching_the_broker(self):
        from strategies.signals import Action

        _add_bar(self.instrument)
        first = place_order(self.account, self.instrument, Action.BUY, 10)
        self.assertEqual(first.status, Order.Status.FILLED)

        second = place_order(self.account, self.instrument, Action.BUY, 10)

        self.assertEqual(second.status, Order.Status.REJECTED)
        self.assertIn("duplicate", second.rejection_reason)

    @patch("execution.services.evaluate")
    def test_risk_rejection_prevents_broker_submission(self, mock_evaluate):
        from risk.engine import RiskCheckResult
        from strategies.signals import Action

        mock_evaluate.return_value = RiskCheckResult(
            approved=False, reason="daily loss limit reached"
        )
        _add_bar(self.instrument)

        order = place_order(self.account, self.instrument, Action.BUY, 10)

        self.assertEqual(order.status, Order.Status.REJECTED)
        self.assertEqual(order.rejection_reason, "daily loss limit reached")
        self.assertEqual(order.trades.count(), 0)
