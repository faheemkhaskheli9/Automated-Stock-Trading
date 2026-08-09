from datetime import datetime, timezone
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from marketdata.models import PriceBar
from strategies.models import ManualSignal, Strategy

from .factories import make_account, make_instrument


class RunTradingCycleCommandTests(TestCase):
    def test_reports_no_orders(self):
        out = StringIO()
        call_command("run_trading_cycle", stdout=out)
        self.assertIn("no orders placed", out.getvalue())

    def test_reports_placed_orders(self):
        account = make_account(cash_balance=100_000)
        instrument = make_instrument()
        bar = PriceBar.objects.create(
            instrument=instrument,
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            open=Decimal("10"),
            high=Decimal("10"),
            low=Decimal("10"),
            close=Decimal("10"),
            volume=100,
        )
        strategy = Strategy.objects.create(
            name="Manual",
            key="manual",
            params={"instrument_id": instrument.id},
            account=account,
            is_active=True,
        )
        strategy.instruments.add(instrument)
        ManualSignal.objects.create(instrument=instrument, date=bar.timestamp.date(), action="buy")

        out = StringIO()
        call_command("run_trading_cycle", stdout=out)

        self.assertIn("1 order(s) placed", out.getvalue())

    @patch("execution.management.commands.run_trading_cycle.run_trading_cycle")
    def test_calls_the_task_function_directly(self, mock_run):
        mock_run.return_value = [1, 2, 3]
        out = StringIO()
        call_command("run_trading_cycle", stdout=out)
        mock_run.assert_called_once_with()
        self.assertIn("3 order(s) placed", out.getvalue())
