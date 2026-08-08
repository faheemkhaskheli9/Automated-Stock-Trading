from datetime import datetime, timezone

from django.db import IntegrityError
from django.test import TestCase

from marketdata.models import Instrument, PriceBar


class InstrumentTests(TestCase):
    def test_str(self):
        instrument = Instrument.objects.create(symbol="ENGRO", exchange="PSX")
        self.assertEqual(str(instrument), "ENGRO (PSX)")

    def test_unique_symbol_per_exchange(self):
        Instrument.objects.create(symbol="ENGRO", exchange="PSX")
        with self.assertRaises(IntegrityError):
            Instrument.objects.create(symbol="ENGRO", exchange="PSX")


class PriceBarTests(TestCase):
    def test_unique_bar_per_instrument_timeframe_timestamp(self):
        instrument = Instrument.objects.create(symbol="ENGRO", exchange="PSX")
        ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
        PriceBar.objects.create(
            instrument=instrument,
            timestamp=ts,
            open=1,
            high=2,
            low=1,
            close=1.5,
            volume=100,
        )
        with self.assertRaises(IntegrityError):
            PriceBar.objects.create(
                instrument=instrument,
                timestamp=ts,
                open=1,
                high=2,
                low=1,
                close=1.5,
                volume=100,
            )
