from datetime import datetime, timezone
from decimal import Decimal

from django.test import TestCase

from marketdata.models import PriceBar
from portfolio.models import Position
from portfolio.tests.factories import make_account, make_instrument
from strategies.signals import Action

from ..checks import check_max_daily_loss, check_max_position_size, get_opening_equity
from ..models import DailyEquitySnapshot


class GetOpeningEquityTests(TestCase):
    def test_creates_snapshot_on_first_call(self):
        account = make_account(cash_balance=1000)
        opening = get_opening_equity(account)
        self.assertEqual(opening, Decimal("1000"))
        self.assertEqual(DailyEquitySnapshot.objects.filter(account=account).count(), 1)

    def test_reuses_existing_snapshot_even_if_equity_later_changes(self):
        account = make_account(cash_balance=1000)
        get_opening_equity(account)

        account.cash_balance = Decimal("1")
        account.save()

        self.assertEqual(get_opening_equity(account), Decimal("1000"))


class CheckMaxDailyLossTests(TestCase):
    def test_approves_when_within_limit(self):
        account = make_account(cash_balance=1000)
        get_opening_equity(account)  # snapshot at 1000
        account.cash_balance = Decimal("990")  # 1% loss
        account.save()

        ok, reason = check_max_daily_loss(account, max_daily_loss_pct=Decimal("2"))

        self.assertTrue(ok)
        self.assertEqual(reason, "")

    def test_rejects_when_loss_exceeds_limit(self):
        account = make_account(cash_balance=1000)
        get_opening_equity(account)
        account.cash_balance = Decimal("900")  # 10% loss
        account.save()

        ok, reason = check_max_daily_loss(account, max_daily_loss_pct=Decimal("2"))

        self.assertFalse(ok)
        self.assertIn("daily loss", reason)


class CheckMaxPositionSizeTests(TestCase):
    def test_sell_always_approved(self):
        account = make_account(cash_balance=1000)
        instrument = make_instrument()
        ok, reason = check_max_position_size(
            account,
            instrument,
            Action.SELL,
            9999,
            Decimal("100"),
            max_position_size_pct=Decimal("1"),
        )
        self.assertTrue(ok)

    def test_buy_within_limit_is_approved(self):
        account = make_account(cash_balance=100_000)
        instrument = make_instrument()
        # 10 shares * 100 = 1000, well under 10% of 100,000 (10,000)
        ok, reason = check_max_position_size(
            account, instrument, Action.BUY, 10, Decimal("100"), max_position_size_pct=Decimal("10")
        )
        self.assertTrue(ok)

    def test_buy_exceeding_limit_is_rejected(self):
        account = make_account(cash_balance=1000)
        instrument = make_instrument()
        ok, reason = check_max_position_size(
            account,
            instrument,
            Action.BUY,
            100,
            Decimal("100"),
            max_position_size_pct=Decimal("10"),
        )
        self.assertFalse(ok)
        self.assertIn("exceed", reason)

    def test_existing_position_counts_toward_the_limit(self):
        account = make_account(cash_balance=100_000)
        instrument = make_instrument()
        PriceBar.objects.create(
            instrument=instrument,
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            open=100,
            high=100,
            low=100,
            close=100,
            volume=1,
        )
        Position.objects.create(
            account=account, instrument=instrument, quantity=90, avg_entry_price=100
        )

        # existing 90*100=9000 + new 20*100=2000 = 11000 > 10% of 100,000 (10,000)
        ok, reason = check_max_position_size(
            account, instrument, Action.BUY, 20, Decimal("100"), max_position_size_pct=Decimal("10")
        )
        self.assertFalse(ok)
