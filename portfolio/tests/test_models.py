from datetime import datetime, timezone
from decimal import Decimal

from django.db import IntegrityError
from django.test import TestCase

from marketdata.models import PriceBar
from portfolio.models import Position

from .factories import make_account, make_instrument


class AccountTests(TestCase):
    def test_equity_with_no_positions_is_cash(self):
        account = make_account(cash_balance=5000)
        self.assertEqual(account.equity, Decimal("5000"))

    def test_equity_includes_position_market_value(self):
        account = make_account(cash_balance=1000)
        instrument = make_instrument()
        PriceBar.objects.create(
            instrument=instrument,
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            open=10,
            high=10,
            low=10,
            close=10,
            volume=100,
        )
        Position.objects.create(
            account=account, instrument=instrument, quantity=50, avg_entry_price=9
        )

        self.assertEqual(account.equity, Decimal("1000") + Decimal("500"))  # 1000 cash + 50*10

    def test_unique_account_name_per_owner(self):
        account = make_account()
        with self.assertRaises(IntegrityError):
            make_account(owner=account.owner)


class PositionTests(TestCase):
    def test_market_value_falls_back_to_avg_entry_price_without_bars(self):
        account = make_account()
        instrument = make_instrument()
        position = Position.objects.create(
            account=account, instrument=instrument, quantity=10, avg_entry_price=Decimal("42.5")
        )
        self.assertEqual(position.market_value, Decimal("425.0"))

    def test_unique_position_per_account_instrument(self):
        account = make_account()
        instrument = make_instrument()
        Position.objects.create(
            account=account, instrument=instrument, quantity=1, avg_entry_price=1
        )
        with self.assertRaises(IntegrityError):
            Position.objects.create(
                account=account, instrument=instrument, quantity=1, avg_entry_price=1
            )
