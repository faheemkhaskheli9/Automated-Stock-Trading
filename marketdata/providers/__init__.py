from .base import Bar, MarketDataProvider, Quote
from .psx import PSXProvider

__all__ = ["Bar", "MarketDataProvider", "Quote", "PSXProvider"]


def get_default_provider() -> MarketDataProvider:
    """The provider used by ingestion tasks/commands unless overridden.

    A single seam so swapping the default (e.g. to a paid feed) later is
    a one-line change here, not a hunt through callers.
    """
    return PSXProvider()
