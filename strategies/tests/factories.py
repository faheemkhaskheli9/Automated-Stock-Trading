from datetime import datetime, timedelta, timezone

from marketdata.providers.base import Bar


def make_bars(closes: list[float], start=datetime(2026, 1, 1, tzinfo=timezone.utc)) -> list[Bar]:
    """One daily Bar per close price, open=high=low=close for simplicity."""
    bars = []
    for i, close in enumerate(closes):
        ts = start + timedelta(days=i)
        bars.append(Bar(timestamp=ts, open=close, high=close, low=close, close=close, volume=1000))
    return bars
