from datetime import date, datetime, timezone
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from backtesting.models import Backtest, BacktestRun
from execution.models import Order
from marketdata.models import Instrument, PriceBar
from modeling.models import ModelPrediction, TradingModel
from portfolio.models import Account, Position
from research.models import NewsItem, ResearchSnapshot
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


class ResearchForecastingApiTests(APITestCase):
    """Phase 7 read endpoints - operator-global, auth required, not owner-scoped."""

    def setUp(self):
        self.engro = Instrument.objects.create(symbol="ENGRO")
        self.luck = Instrument.objects.create(symbol="LUCK")
        NewsItem.objects.create(
            symbol="ENGRO",
            headline="Engro posts record profit",
            url="https://example.com/a",
            url_hash="hash-a",
            published_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            sentiment=0.6,
        )
        NewsItem.objects.create(
            symbol="LUCK",
            headline="Lucky Cement expands",
            url="https://example.com/b",
            url_hash="hash-b",
            published_at=datetime(2026, 1, 3, tzinfo=timezone.utc),
        )
        ResearchSnapshot.objects.create(
            symbol="ENGRO",
            as_of=datetime(2026, 1, 2, tzinfo=timezone.utc),
            features={"rsi_14": 55.0},
            provider_keys=["technical"],
        )
        self.model = TradingModel.objects.create(
            name="Ridge-1", estimator_key="ridge", is_active=False
        )
        ModelPrediction.objects.create(
            model=self.model,
            instrument=self.engro,
            as_of=datetime(2026, 1, 2, tzinfo=timezone.utc),
            target_date=date(2026, 1, 3),
            predicted_value=101.5,
        )
        self.backtest = Backtest.objects.create(name="BT-1", model=self.model)
        BacktestRun.objects.create(backtest=self.backtest, status=BacktestRun.Status.SUCCESS)

    def test_all_endpoints_require_authentication(self):
        for name in (
            "newsitem-list",
            "researchsnapshot-list",
            "modelprediction-list",
            "tradingmodel-list",
            "backtest-list",
            "backtestrun-list",
        ):
            self.assertEqual(self.client.get(reverse(name)).status_code, status.HTTP_403_FORBIDDEN)

    def test_authenticated_user_sees_global_rows(self):
        self.client.force_authenticate(make_user())

        self.assertEqual(self.client.get(reverse("newsitem-list")).data["count"], 2)
        self.assertEqual(self.client.get(reverse("researchsnapshot-list")).data["count"], 1)
        self.assertEqual(self.client.get(reverse("modelprediction-list")).data["count"], 1)
        self.assertEqual(self.client.get(reverse("backtest-list")).data["count"], 1)

    def test_symbol_filter(self):
        self.client.force_authenticate(make_user())

        response = self.client.get(reverse("newsitem-list"), {"symbol": "engro"})
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["symbol"], "ENGRO")

        response = self.client.get(reverse("modelprediction-list"), {"symbol": "luck"})
        self.assertEqual(response.data["count"], 0)

    def test_backtest_nests_runs(self):
        self.client.force_authenticate(make_user())
        response = self.client.get(reverse("backtest-list"))
        self.assertEqual(len(response.data["results"][0]["runs"]), 1)

    def test_trading_model_is_active_toggle(self):
        self.client.force_authenticate(make_user())
        url = reverse("tradingmodel-detail", args=[self.model.id])

        response = self.client.patch(url, {"is_active": True}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.model.refresh_from_db()
        self.assertTrue(self.model.is_active)

    def test_trading_model_config_is_read_only(self):
        self.client.force_authenticate(make_user())
        url = reverse("tradingmodel-detail", args=[self.model.id])

        self.client.patch(url, {"estimator_key": "elasticnet"}, format="json")

        self.model.refresh_from_db()
        self.assertEqual(self.model.estimator_key, "ridge")

    def test_trading_model_cannot_be_deleted(self):
        self.client.force_authenticate(make_user())
        url = reverse("tradingmodel-detail", args=[self.model.id])
        self.assertEqual(self.client.delete(url).status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_predictions_are_read_only(self):
        self.client.force_authenticate(make_user())
        response = self.client.post(reverse("modelprediction-list"), {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)


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
