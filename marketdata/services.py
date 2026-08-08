"""Ingestion logic shared by the management command and the Celery task -
neither should know more than "sync this instrument" / "sync everything
active".
"""

import logging
from datetime import date

from .models import Instrument, PriceBar
from .providers import MarketDataProvider, get_default_provider

logger = logging.getLogger(__name__)


def sync_instrument_history(
    instrument: Instrument,
    provider: MarketDataProvider | None = None,
    start: date | None = None,
    end: date | None = None,
) -> int:
    """Fetch and upsert history for one instrument. Returns the number of
    bars written (created or updated)."""
    provider = provider or get_default_provider()
    bars = provider.get_history(instrument.symbol, start=start, end=end)
    if not bars:
        return 0

    PriceBar.objects.bulk_create(
        [
            PriceBar(
                instrument=instrument,
                timeframe=PriceBar.Timeframe.DAILY,
                timestamp=bar.timestamp,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
                is_anomaly=bar.is_anomaly,
            )
            for bar in bars
        ],
        update_conflicts=True,
        unique_fields=["instrument", "timeframe", "timestamp"],
        update_fields=["open", "high", "low", "close", "volume", "is_anomaly"],
    )
    return len(bars)


def sync_active_instruments(
    provider: MarketDataProvider | None = None,
    start: date | None = None,
    end: date | None = None,
) -> dict[str, int]:
    """Sync history for every active Instrument. Returns {symbol: bars_written},
    continuing past per-symbol failures rather than aborting the whole run."""
    provider = provider or get_default_provider()
    results = {}
    for instrument in Instrument.objects.filter(is_active=True):
        try:
            results[instrument.symbol] = sync_instrument_history(
                instrument, provider=provider, start=start, end=end
            )
        except Exception:
            logger.exception("Failed to sync history for %s", instrument.symbol)
            results[instrument.symbol] = 0
    return results
