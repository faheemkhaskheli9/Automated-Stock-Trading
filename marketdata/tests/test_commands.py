from io import StringIO
from unittest.mock import patch

from django.core.management import CommandError, call_command
from django.test import TestCase

from marketdata.models import Instrument, PriceBar

from .factories import FakeProvider


class SyncMarketDataCommandTests(TestCase):
    def test_unknown_symbol_raises(self):
        with self.assertRaises(CommandError):
            call_command("sync_market_data", symbol="NOPE")

    @patch("marketdata.management.commands.sync_market_data.sync_instrument_history")
    def test_single_symbol(self, mock_sync):
        mock_sync.return_value = 2
        Instrument.objects.create(symbol="ENGRO")

        out = StringIO()
        call_command("sync_market_data", symbol="engro", stdout=out)

        mock_sync.assert_called_once()
        self.assertIn("2 bars written", out.getvalue())

    @patch("marketdata.services.get_default_provider")
    def test_all_active(self, mock_get_provider):
        mock_get_provider.return_value = FakeProvider()
        Instrument.objects.create(symbol="ENGRO", is_active=True)

        out = StringIO()
        call_command("sync_market_data", stdout=out)

        self.assertEqual(PriceBar.objects.count(), 2)
        self.assertIn("Synced 1 instrument(s)", out.getvalue())
