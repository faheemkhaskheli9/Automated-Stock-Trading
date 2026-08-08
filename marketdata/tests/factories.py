from datetime import datetime, timezone

from ..providers.base import Bar


def make_bar(
    day: int = 1,
    open=100.0,
    high=105.0,
    low=99.0,
    close=102.0,
    volume=10_000,
    is_anomaly=False,
) -> Bar:
    return Bar(
        timestamp=datetime(2026, 1, day, tzinfo=timezone.utc),
        open=open,
        high=high,
        low=low,
        close=close,
        volume=volume,
        is_anomaly=is_anomaly,
    )


class FakeProvider:
    """A MarketDataProvider stub for tests - avoids any real PSX/network call."""

    def __init__(self, history: list[Bar] | None = None, quote=None):
        self._history = history if history is not None else [make_bar(1), make_bar(2)]
        self._quote = quote

    def get_history(self, symbol, start=None, end=None):
        return self._history

    def get_latest(self, symbol):
        return self._quote
