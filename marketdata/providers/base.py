"""Market data provider interface.

Isolating PSX-specific fetching behind this interface means the ingestion
code (management command + Celery task) and everything downstream never
import `psxdata` directly - swapping to the paid PSX data-vending feed, or
adding another exchange, is a new provider class, not a rewrite.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class Bar:
    """One normalized OHLCV bar, provider-agnostic."""

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    is_anomaly: bool = False


@dataclass(frozen=True)
class Quote:
    """A latest-price snapshot, provider-agnostic."""

    symbol: str
    price: float
    as_of: datetime


class MarketDataProvider(ABC):
    """Interface every market data source (PSX scraper, paid feed, ...)
    must implement."""

    @abstractmethod
    def get_history(
        self, symbol: str, start: date | None = None, end: date | None = None
    ) -> list[Bar]:
        """Return historical OHLCV bars for `symbol` in the inclusive
        [start, end] date range, oldest first. Empty list if unavailable."""

    @abstractmethod
    def get_latest(self, symbol: str) -> Quote | None:
        """Return the latest known price for `symbol`, or None if
        unavailable."""
