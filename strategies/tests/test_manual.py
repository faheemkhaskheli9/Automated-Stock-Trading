from datetime import datetime, timezone

from django.test import TestCase

from marketdata.models import Instrument
from strategies.manual import ManualSignalStrategy
from strategies.models import ManualSignal
from strategies.signals import Action

from .factories import make_bars


class ManualSignalStrategyTests(TestCase):
    def setUp(self):
        self.instrument = Instrument.objects.create(symbol="ENGRO")

    def test_requires_instrument_id(self):
        with self.assertRaises(ValueError):
            ManualSignalStrategy()

    def test_uses_matching_manual_entry(self):
        bars = make_bars([100, 101], start=datetime(2026, 1, 1, tzinfo=timezone.utc))
        ManualSignal.objects.create(
            instrument=self.instrument, date=bars[0].timestamp.date(), action="buy"
        )

        strategy = ManualSignalStrategy(instrument_id=self.instrument.id)
        signals = strategy.generate_signals(bars)

        self.assertEqual(signals[0].action, Action.BUY)
        self.assertEqual(signals[1].action, Action.HOLD)

    def test_no_entry_holds(self):
        bars = make_bars([100])
        strategy = ManualSignalStrategy(instrument_id=self.instrument.id)
        signals = strategy.generate_signals(bars)
        self.assertEqual(signals[0].action, Action.HOLD)
