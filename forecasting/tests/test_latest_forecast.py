"""Tests for ``forecasting.services.latest_forecast`` - the best-effort
next-session estimate behind the symbol-detail dashboard panel."""

from datetime import datetime, timedelta
from datetime import timezone as tz

from django.test import TestCase

from forecasting.services import latest_forecast
from marketdata.models import Instrument, PriceBar


class LatestForecastTests(TestCase):
    def setUp(self):
        self.instrument = Instrument.objects.create(symbol="OGDC", name="Oil & Gas Dev")
        start = datetime(2026, 1, 1, tzinfo=tz.utc)
        for i in range(90):
            price = 100 + i * 0.4
            PriceBar.objects.create(
                instrument=self.instrument,
                timeframe=PriceBar.Timeframe.DAILY,
                timestamp=start + timedelta(days=i),
                open=price,
                high=price + 1.5,
                low=price - 1.5,
                close=price + (0.5 if i % 2 else -0.5),
                volume=1_000 + i,
            )
        self.last_close = float(
            PriceBar.objects.filter(instrument=self.instrument).latest("timestamp").close
        )

    def test_naive_returns_last_close_and_a_future_weekday(self):
        result = latest_forecast("OGDC", "naive")
        self.assertIsNone(result.error)
        self.assertIsNotNone(result.prediction)
        self.assertAlmostEqual(result.prediction.predicted_close, self.last_close, places=6)
        self.assertLess(result.target_date.weekday(), 5)
        last_session = (
            PriceBar.objects.filter(instrument=self.instrument).latest("timestamp").timestamp.date()
        )
        self.assertGreater(result.target_date, last_session)

    def test_trainable_predictor_is_fitted_then_predicts(self):
        result = latest_forecast("OGDC", "drift")
        self.assertIsNone(result.error)
        self.assertIsNotNone(result.prediction)
        self.assertEqual(result.display_name, "Random walk with fitted drift")
        self.assertGreater(result.prediction.predicted_close, 0)

    def test_unknown_predictor_key_is_reported_not_raised(self):
        result = latest_forecast("OGDC", "no-such-model")
        self.assertIsNone(result.prediction)
        self.assertIn("no-such-model", result.error)

    def test_missing_history_is_reported_not_raised(self):
        Instrument.objects.create(symbol="HBL", name="Habib Bank")
        result = latest_forecast("HBL", "naive")
        self.assertIsNone(result.prediction)
        self.assertEqual(result.error, "No saved history to forecast from.")

    def test_unknown_symbol_is_reported_not_raised(self):
        result = latest_forecast("NOPE", "naive")
        self.assertIsNone(result.prediction)
        self.assertEqual(result.error, "No saved history to forecast from.")
