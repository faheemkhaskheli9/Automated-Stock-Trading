from django.test import TestCase

from marketdata.models import Instrument, PriceBar
from marketdata.services import sync_active_instruments, sync_instrument_history

from .factories import FakeProvider, make_bar


class SyncInstrumentHistoryTests(TestCase):
    def test_writes_bars(self):
        instrument = Instrument.objects.create(symbol="ENGRO")
        count = sync_instrument_history(instrument, provider=FakeProvider())

        self.assertEqual(count, 2)
        self.assertEqual(PriceBar.objects.filter(instrument=instrument).count(), 2)

    def test_upserts_on_rerun(self):
        instrument = Instrument.objects.create(symbol="ENGRO")
        sync_instrument_history(instrument, provider=FakeProvider([make_bar(1, close=100)]))
        sync_instrument_history(instrument, provider=FakeProvider([make_bar(1, close=999)]))

        self.assertEqual(PriceBar.objects.filter(instrument=instrument).count(), 1)
        self.assertEqual(float(PriceBar.objects.get(instrument=instrument).close), 999)

    def test_no_bars_returns_zero(self):
        instrument = Instrument.objects.create(symbol="ENGRO")
        count = sync_instrument_history(instrument, provider=FakeProvider([]))
        self.assertEqual(count, 0)


class SyncActiveInstrumentsTests(TestCase):
    def test_only_syncs_active(self):
        Instrument.objects.create(symbol="ENGRO", is_active=True)
        Instrument.objects.create(symbol="DELISTED", is_active=False)

        results = sync_active_instruments(provider=FakeProvider())

        self.assertEqual(set(results.keys()), {"ENGRO"})

    def test_one_symbol_failing_does_not_abort_others(self):
        Instrument.objects.create(symbol="GOOD", is_active=True)
        Instrument.objects.create(symbol="BAD", is_active=True)

        class FlakyProvider(FakeProvider):
            def get_history(self, symbol, start=None, end=None):
                if symbol == "BAD":
                    raise RuntimeError("boom")
                return super().get_history(symbol, start, end)

        results = sync_active_instruments(provider=FlakyProvider())

        self.assertEqual(results["GOOD"], 2)
        self.assertEqual(results["BAD"], 0)
