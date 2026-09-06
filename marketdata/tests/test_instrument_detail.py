from datetime import date, datetime, timedelta
from datetime import timezone as tz

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from marketdata.models import Instrument, PriceBar
from marketdata.views import _ema, _sma
from modeling.models import ModelPrediction, TradingModel


class MovingAverageHelperTests(TestCase):
    def test_sma_is_none_until_window_is_full(self):
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        self.assertEqual(_sma(values, 3), [None, None, 2.0, 3.0, 4.0])

    def test_ema_seeds_with_sma_then_smooths(self):
        values = [float(v) for v in range(1, 11)]
        out = _ema(values, 4)
        self.assertEqual(out[:3], [None, None, None])
        self.assertAlmostEqual(out[3], 2.5)  # SMA of 1..4
        k = 2 / 5
        self.assertAlmostEqual(out[4], 5 * k + 2.5 * (1 - k))

    def test_short_series_returns_all_none(self):
        self.assertEqual(_ema([1.0, 2.0], 5), [None, None])


class InstrumentDetailPageTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser("viewer", password="test-pass")
        self.client.force_login(self.user)
        self.ogdc = Instrument.objects.create(symbol="OGDC", name="Oil & Gas Dev", sector="Energy")
        start = datetime(2026, 1, 1, tzinfo=tz.utc)
        for i in range(250):
            price = 100 + i * 0.5
            PriceBar.objects.create(
                instrument=self.ogdc,
                timeframe=PriceBar.Timeframe.DAILY,
                timestamp=start + timedelta(days=i),
                open=price,
                high=price + 2,
                low=price - 2,
                close=price + (1 if i % 2 else -1),
                volume=1000 + i,
            )
        self.url = reverse("marketdata:instrument_detail", args=["OGDC"])

    def test_login_required(self):
        self.client.logout()
        self.assertRedirects(self.client.get(self.url), f"/login/?next={self.url}")

    def test_unknown_symbol_is_404(self):
        self.assertEqual(
            self.client.get(reverse("marketdata:instrument_detail", args=["NOPE"])).status_code, 404
        )

    def test_renders_candles_and_default_range(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Candlestick")
        self.assertContains(response, "<rect")
        # Default window is 180 sessions even though 250 are stored.
        self.assertEqual(response.context["shown"], 180)
        self.assertEqual(response.context["bar_count"], 250)

    def test_all_range_shows_every_bar(self):
        response = self.client.get(self.url, {"days": "0"})
        self.assertEqual(response.context["shown"], 250)

    def test_invalid_range_falls_back_to_default(self):
        response = self.client.get(self.url, {"days": "banana"})
        self.assertEqual(response.context["days"], 180)

    def test_sma_overlay_toggled_via_query(self):
        response = self.client.get(self.url, {"sma": ["20", "50"]})
        keys = [line["key"] for line in response.context["overlay_lines"]]
        self.assertEqual(keys, ["sma20", "sma50"])
        self.assertContains(response, "SMA 20")
        self.assertContains(response, "<polyline")

    def test_ema_and_unknown_period_filtered(self):
        response = self.client.get(self.url, {"ema": ["20", "7"]})
        keys = [line["key"] for line in response.context["overlay_lines"]]
        self.assertEqual(keys, ["ema20"])

    def test_overlay_polyline_is_warm_at_left_edge(self):
        # With extra lookback loaded, a 50-period SMA has a value from the very
        # first visible bar, so the polyline spans the whole width.
        response = self.client.get(self.url, {"days": "90", "sma": ["50"]})
        points = response.context["overlay_lines"][0]["points"].split()
        self.assertEqual(len(points), 90)

    def test_prediction_panel_when_present(self):
        model = TradingModel.objects.create(name="Ridge H1", estimator_key="ridge")
        ModelPrediction.objects.create(
            model=model,
            instrument=self.ogdc,
            as_of=datetime(2026, 6, 1, tzinfo=tz.utc),
            target_date=date(2026, 6, 2),
            predicted_value=205.0,
        )
        response = self.client.get(self.url)
        self.assertContains(response, "Ridge H1")
        self.assertContains(response, "205.00")

    def test_no_history_shows_empty_state(self):
        Instrument.objects.create(symbol="HBL", name="Habib Bank")
        response = self.client.get(reverse("marketdata:instrument_detail", args=["HBL"]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No stored history")
        self.assertEqual(response.context["candles"], [])

    def test_instruments_table_links_to_detail(self):
        response = self.client.get(reverse("marketdata:instruments"))
        self.assertContains(response, f'href="{self.url}"')

    def test_menubar_marks_instruments_active(self):
        body = self.client.get(self.url).content.decode()
        self.assertIn(f'href="{reverse("marketdata:instruments")}" aria-current="page"', body)
        self.assertNotIn(f'href="{reverse("marketdata:dashboard")}" aria-current="page"', body)
