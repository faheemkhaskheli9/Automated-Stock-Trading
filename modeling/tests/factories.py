import math
from datetime import datetime, timedelta, timezone

import pandas as pd

from marketdata.models import Instrument, PriceBar

UTC_START = datetime(2025, 1, 1, tzinfo=timezone.utc)


def make_instrument(symbol="ENGRO", exchange="PSX", **kw):
    obj, _ = Instrument.objects.get_or_create(
        exchange=exchange, symbol=symbol, defaults={"name": symbol, "is_active": True, **kw}
    )
    return obj


def make_price_series(instrument, n=420, start=UTC_START, base=100.0, phase=0.0):
    """A smooth trending+cyclical close series - enough signal for a fit and
    enough bars (>60) for every technical indicator."""
    bars = []
    for i in range(n):
        close = base + 18 * math.sin(i / 14 + phase) + i * 0.04
        bars.append(
            PriceBar(
                instrument=instrument,
                timeframe=PriceBar.Timeframe.DAILY,
                timestamp=start + timedelta(days=i),
                open=close * 0.999,
                high=close * 1.012,
                low=close * 0.988,
                close=close,
                volume=10_000 + i * 3,
            )
        )
    PriceBar.objects.bulk_create(bars)
    return bars


def ohlcv_frame(n=200, start=UTC_START, base=100.0, tz="Asia/Karachi"):
    """In-memory OHLCV frame (tz-aware daily index) for pure feature/target tests."""
    idx = pd.date_range(start=pd.Timestamp(start), periods=n, freq="D", tz="UTC").tz_convert(tz)
    close = pd.Series(
        [base + 18 * math.sin(i / 14) + i * 0.04 for i in range(n)], index=idx, dtype=float
    )
    return pd.DataFrame(
        {
            "open": close * 0.999,
            "high": close * 1.012,
            "low": close * 0.988,
            "close": close,
            "volume": pd.Series(range(10_000, 10_000 + n), index=idx, dtype=float),
        }
    )
