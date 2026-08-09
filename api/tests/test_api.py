from datetime import datetime, timezone
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from execution.models import Order
from marketdata.models import Instrument, PriceBar
from portfolio.models import Account, Position
from strategies.models import Strategy


def make_user(username="trader", **kwargs):
    return get_user_model().objects.create_user(username=username, password="pw", **kwargs)


class InstrumentApiTests(APITestCase):
    def test_requires_authentication(self):
        response = self.client.get(reverse("instrument-list"))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_authenticated_user_can_list(self):
        Instrument.objects.create(symbol="ENGRO")
        self.client.force_authenticate(make_user())

        response = self.client.get(reverse("instrument-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)


class OwnerScopingTests(APITestCase):
    """Covers Account/Position/Order - all use the same OwnerScopedMixin."""

    def setUp(self):
        self.owner = make_user("owner")
        self.other = make_user("other")
        self.staff = make_user("staff", is_staff=True)
        self.instrument = Instrument.objects.create(symbol="ENGRO")
        self.account = Account.objects.create(
            owner=self.owner, name="Main", cash_balance=Decimal("1000")
        )
        self.position = Position.objects.create(
            account=self.account,
            instrument=self.instrument,
            quantity=10,
            avg_entry_price=Decimal("10"),
        )

    def test_owner_sees_their_own_account(self):
        self.client.force_authenticate(self.owner)
        response = self.client.get(reverse("account-list"))
        self.assertEqual(response.data["count"], 1)

    def test_other_user_sees_nothing(self):
        self.client.force_authenticate(self.other)
        response = self.client.get(reverse("account-list"))
        self.assertEqual(response.data["count"], 0)

    def test_staff_sees_everything(self):
        self.client.force_authenticate(self.staff)
        response = self.client.get(reverse("account-list"))
        self.assertEqual(response.data["count"], 1)

    def test_position_is_scoped_through_account(self):
        self.client.force_authenticate(self.other)
        response = self.client.get(reverse("position-list"))
        self.assertEqual(response.data["count"], 0)

        self.client.force_authenticate(self.owner)
        response = self.client.get(reverse("position-list"))
        self.assertEqual(response.data["count"], 1)
        # market_value falls back to avg_entry_price (no PriceBar exists), so PnL is flat 0.
        self.assertEqual(Decimal(response.data["results"][0]["unrealized_pnl"]), Decimal("0"))


class StrategyToggleTests(APITestCase):
    def setUp(self):
        self.owner = make_user("owner")
        self.account = Account.objects.create(
            owner=self.owner, name="Main", cash_balance=Decimal("1000")
        )
        self.strategy = Strategy.objects.create(
            name="MA", key="ma_crossover", account=self.account, is_active=False
        )
        self.client.force_authenticate(self.owner)

    def test_can_toggle_is_active(self):
        url = reverse("strategy-detail", args=[self.strategy.id])
        response = self.client.patch(url, {"is_active": True}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.strategy.refresh_from_db()
        self.assertTrue(self.strategy.is_active)

    def test_cannot_change_read_only_fields(self):
        url = reverse("strategy-detail", args=[self.strategy.id])
        self.client.patch(url, {"key": "rsi"}, format="json")

        self.strategy.refresh_from_db()
        self.assertEqual(self.strategy.key, "ma_crossover")  # unchanged

    def test_cannot_delete(self):
        url = reverse("strategy-detail", args=[self.strategy.id])
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_other_user_cannot_see_or_toggle(self):
        other = make_user("other")
        self.client.force_authenticate(other)
        url = reverse("strategy-detail", args=[self.strategy.id])

        response = self.client.patch(url, {"is_active": True}, format="json")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class OrderApiTests(APITestCase):
    def test_orders_are_scoped_and_include_nested_trades(self):
        owner = make_user("owner")
        account = Account.objects.create(owner=owner, name="Main", cash_balance=Decimal("1000"))
        instrument = Instrument.objects.create(symbol="ENGRO")
        Order.objects.create(account=account, instrument=instrument, side="buy", quantity=10)

        self.client.force_authenticate(owner)
        response = self.client.get(reverse("order-list"))

        self.assertEqual(response.data["count"], 1)
        self.assertIn("trades", response.data["results"][0])


class PriceBarApiTests(APITestCase):
    def test_filters_by_symbol_query_param(self):
        engro = Instrument.objects.create(symbol="ENGRO")
        luck = Instrument.objects.create(symbol="LUCK")
        for instrument in (engro, luck):
            PriceBar.objects.create(
                instrument=instrument,
                timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
                open=1,
                high=1,
                low=1,
                close=1,
                volume=1,
            )
        self.client.force_authenticate(make_user())

        response = self.client.get(reverse("pricebar-list"), {"symbol": "engro"})

        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["instrument"], "ENGRO")
