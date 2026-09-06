from datetime import date, datetime
from datetime import timezone as tz

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from marketdata.models import Instrument, PriceBar
from modeling.models import ModelPrediction, TradingModel


class InstrumentsPageTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser("viewer", password="test-pass")
        self.client.force_login(self.user)
        self.url = reverse("marketdata:instruments")
        self.ogdc = Instrument.objects.create(symbol="OGDC", name="Oil & Gas Dev", sector="Energy")
        self.hbl = Instrument.objects.create(symbol="HBL", name="Habib Bank", sector="Banking")
        for day, close in ((5, 105), (6, 108)):
            PriceBar.objects.create(
                instrument=self.ogdc,
                timeframe=PriceBar.Timeframe.DAILY,
                timestamp=datetime(2026, 1, day, tzinfo=tz.utc),
                open=100,
                high=112,
                low=99,
                close=close,
                volume=1000,
            )

    def test_login_required(self):
        self.client.logout()
        self.assertRedirects(self.client.get(self.url), f"/login/?next={self.url}")

    def test_lists_instruments_with_latest_close(self):
        response = self.client.get(self.url)
        self.assertContains(response, "OGDC")
        self.assertContains(response, "HBL")
        # The most recent daily bar wins, not the older one.
        self.assertContains(response, "108.00")

    def test_search_by_symbol(self):
        response = self.client.get(self.url, {"q": "ogd"})
        self.assertContains(response, "<strong>OGDC</strong>", html=False)
        self.assertNotContains(response, "<strong>HBL</strong>", html=False)

    def test_search_by_name(self):
        response = self.client.get(self.url, {"q": "habib"})
        self.assertContains(response, "<strong>HBL</strong>", html=False)
        self.assertNotContains(response, "<strong>OGDC</strong>", html=False)

    def test_prediction_vs_actual_shown(self):
        model = TradingModel.objects.create(name="Ridge H1", estimator_key="ridge")
        ModelPrediction.objects.create(
            model=model,
            instrument=self.ogdc,
            as_of=datetime(2026, 1, 6, tzinfo=tz.utc),
            target_date=date(2026, 1, 7),
            predicted_value=110.0,
            actual_value=109.0,
            abs_error=1.0,
        )
        response = self.client.get(self.url)
        self.assertContains(response, "Ridge H1")
        self.assertContains(response, "110.00")
        self.assertContains(response, "109.00")

    def test_pending_actual_and_missing_forecast(self):
        model = TradingModel.objects.create(name="GB H1", estimator_key="gradient_boosting")
        ModelPrediction.objects.create(
            model=model,
            instrument=self.ogdc,
            as_of=datetime(2026, 1, 6, tzinfo=tz.utc),
            target_date=date(2026, 1, 7),
            predicted_value=110.0,
        )
        response = self.client.get(self.url)
        self.assertContains(response, "pending")  # OGDC actual not backfilled
        self.assertContains(response, "no forecast")  # HBL has no prediction

    def test_menubar_has_active_instruments_link(self):
        response = self.client.get(self.url)
        marker = f'href="{self.url}" aria-current="page"'
        self.assertIn(marker, response.content.decode())
        self.assertNotIn(
            f'href="{reverse("marketdata:dashboard")}" aria-current="page"',
            response.content.decode(),
        )
