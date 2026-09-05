from datetime import datetime, timedelta, timezone

from marketdata.models import Instrument, PriceBar


def make_instrument(symbol="ENGRO", exchange="PSX", **kw):
    obj, _ = Instrument.objects.get_or_create(
        exchange=exchange, symbol=symbol, defaults={"name": symbol, "is_active": True, **kw}
    )
    return obj


def make_price_series(instrument, closes, start=datetime(2026, 1, 1, tzinfo=timezone.utc)):
    """Create one daily PriceBar per close in `closes`, consecutive days."""
    bars = []
    for i, close in enumerate(closes):
        ts = start + timedelta(days=i)
        bars.append(
            PriceBar(
                instrument=instrument,
                timeframe=PriceBar.Timeframe.DAILY,
                timestamp=ts,
                open=close,
                high=close * 1.01,
                low=close * 0.99,
                close=close,
                volume=10_000 + i,
            )
        )
    PriceBar.objects.bulk_create(bars)
    return bars
