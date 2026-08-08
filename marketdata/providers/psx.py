"""PSX market data provider, backed by the open-source `psxdata` scraper
(https://github.com/mtauha/psxdata). There is no official free PSX API -
this scrapes the public PSX site, so treat failures/rate limiting as
expected and let callers retry rather than assuming reliability.
"""

import logging
from datetime import date

from django.utils import timezone
from psxdata import PSXClient
from psxdata.exceptions import PSXDataError

from .base import Bar, MarketDataProvider, Quote

logger = logging.getLogger(__name__)

# Common base for every psxdata failure mode (connection, server, parse,
# rate limit, unknown/delisted symbol, ...) - worth letting a caller
# retry/backfill later rather than crash the whole ingestion run over one
# bad symbol.
PROVIDER_ERRORS = (PSXDataError,)


class PSXProvider(MarketDataProvider):
    def __init__(self, client: PSXClient | None = None):
        self._client = client or PSXClient()

    def get_history(
        self, symbol: str, start: date | None = None, end: date | None = None
    ) -> list[Bar]:
        try:
            df = self._client.stocks(symbol, start=start, end=end)
        except PROVIDER_ERRORS as exc:
            logger.warning("PSX history fetch failed for %s: %s", symbol, exc)
            return []

        if df.empty:
            return []

        bars = []
        for row in df.itertuples(index=False):
            ts = row.date
            if timezone.is_naive(ts):
                ts = timezone.make_aware(ts, timezone.get_default_timezone())
            bars.append(
                Bar(
                    timestamp=ts,
                    open=float(row.open),
                    high=float(row.high),
                    low=float(row.low),
                    close=float(row.close),
                    volume=int(row.volume),
                    is_anomaly=bool(getattr(row, "is_anomaly", False)),
                )
            )
        return bars

    def get_latest(self, symbol: str) -> Quote | None:
        try:
            df = self._client.quote(symbol)
        except PROVIDER_ERRORS as exc:
            logger.warning("PSX quote fetch failed for %s: %s", symbol, exc)
            return None

        if df.empty or "price" not in df.columns:
            return None

        price = df.iloc[0]["price"]
        if price is None:
            return None

        return Quote(symbol=symbol.upper(), price=float(price), as_of=timezone.now())
