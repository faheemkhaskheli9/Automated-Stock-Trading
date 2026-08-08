from datetime import datetime
from unittest.mock import MagicMock

import pandas as pd
from django.test import SimpleTestCase
from psxdata.exceptions import PSXConnectionError

from marketdata.providers.psx import PSXProvider


class PSXProviderGetHistoryTests(SimpleTestCase):
    def test_maps_dataframe_rows_to_bars(self):
        client = MagicMock()
        client.stocks.return_value = pd.DataFrame(
            [
                {
                    "date": datetime(2026, 1, 1),
                    "open": 100.0,
                    "high": 105.0,
                    "low": 99.0,
                    "close": 102.0,
                    "volume": 1000,
                    "is_anomaly": False,
                }
            ]
        )
        provider = PSXProvider(client=client)

        bars = provider.get_history("engro")

        client.stocks.assert_called_once_with("engro", start=None, end=None)
        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0].close, 102.0)
        self.assertEqual(bars[0].volume, 1000)
        self.assertFalse(bars[0].is_anomaly)

    def test_empty_dataframe_returns_empty_list(self):
        client = MagicMock()
        client.stocks.return_value = pd.DataFrame()
        provider = PSXProvider(client=client)

        self.assertEqual(provider.get_history("ENGRO"), [])

    def test_provider_error_is_swallowed_and_returns_empty_list(self):
        client = MagicMock()
        client.stocks.side_effect = PSXConnectionError("network down")
        provider = PSXProvider(client=client)

        self.assertEqual(provider.get_history("ENGRO"), [])


class PSXProviderGetLatestTests(SimpleTestCase):
    def test_returns_quote(self):
        client = MagicMock()
        client.quote.return_value = pd.DataFrame([{"symbol": "ENGRO", "price": 310.5}])
        provider = PSXProvider(client=client)

        quote = provider.get_latest("engro")

        self.assertIsNotNone(quote)
        self.assertEqual(quote.symbol, "ENGRO")
        self.assertEqual(quote.price, 310.5)

    def test_missing_symbol_returns_none(self):
        client = MagicMock()
        client.quote.return_value = pd.DataFrame()
        provider = PSXProvider(client=client)

        self.assertIsNone(provider.get_latest("UNKNOWN"))
