"""News-headline features.

Ingestion: pull configured RSS feeds with ``feedparser``, score each
headline's sentiment with VADER, upsert into `NewsItem` keyed on a hash of
the URL (idempotent re-ingestion - per the knowledge-base
"chunking-and-embedding-ingestion" pattern: stable idempotency key + source
citation kept on every row).

Both ``feedparser`` and ``vaderSentiment`` are soft-imported: the app, its
migrations, and the point-in-time feature math all work without them
installed; only live ingestion needs them (they're in requirements.txt for
deployed environments).

Features (all windowed strictly to ``published_at <= as_of``):
``news.count_{7,30}d``, ``news.sentiment_mean_{7,30}d``,
``news.sentiment_last``, ``news.sentiment_trend`` (7d mean minus 30d mean).
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone

from django.conf import settings

from ..models import NewsItem
from .base import FeatureBundle, FeatureProvider, register_feature_provider

logger = logging.getLogger(__name__)

NAMESPACE = "news"

# Per-exchange default feeds; override via settings.RESEARCH_NEWS_FEEDS.
DEFAULT_FEEDS: dict[str, list[str]] = {
    "PSX": [
        "https://www.brecorder.com/feeds/latest-news",
        "https://profit.pakistantoday.com.pk/feed/",
    ],
}


def _feeds_for(exchange: str) -> list[str]:
    configured = getattr(settings, "RESEARCH_NEWS_FEEDS", None)
    if configured:
        return configured.get(exchange, [])
    return DEFAULT_FEEDS.get(exchange, [])


def url_hash(url: str) -> str:
    return hashlib.sha256(url.strip().encode("utf-8")).hexdigest()


def score_sentiment(text: str) -> float | None:
    try:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    except ImportError:
        return None
    return SentimentIntensityAnalyzer().polarity_scores(text or "")["compound"]


def _matched_symbols(text: str, symbols: list[str]) -> list[str]:
    upper = (text or "").upper()
    return [s for s in symbols if s.upper() in upper]


def ingest_feeds(exchange: str = "PSX", symbols: list[str] | None = None) -> int:
    """Fetch every configured feed for ``exchange`` and upsert matching
    headlines. Returns the number of `NewsItem` rows created. A headline is
    attached to a symbol when the ticker appears in its title/summary."""
    try:
        import feedparser
    except ImportError:
        logger.warning("news.ingest_feeds: feedparser not installed - skipping")
        return 0

    from marketdata.models import Instrument

    if symbols is None:
        symbols = list(
            Instrument.objects.filter(exchange=exchange, is_active=True).values_list(
                "symbol", flat=True
            )
        )
    if not symbols:
        return 0

    created = 0
    for feed_url in _feeds_for(exchange):
        try:
            parsed = feedparser.parse(feed_url)
        except Exception:
            logger.exception("news.ingest_feeds: failed to parse %s", feed_url)
            continue
        source = (parsed.feed.get("title") if getattr(parsed, "feed", None) else "") or feed_url
        for entry in getattr(parsed, "entries", []):
            title = entry.get("title", "")
            summary = entry.get("summary", "")
            link = entry.get("link", "")
            if not link or not title:
                continue
            matched = _matched_symbols(f"{title} {summary}", symbols)
            if not matched:
                continue
            published = _entry_datetime(entry)
            sentiment = score_sentiment(title)
            for symbol in matched:
                # url_hash is unique per article; namespace it by symbol so
                # one headline mentioning two tickers yields two rows.
                h = url_hash(f"{symbol}|{link}")
                _, was_created = NewsItem.objects.get_or_create(
                    url_hash=h,
                    defaults={
                        "symbol": symbol,
                        "exchange": exchange,
                        "headline": title[:512],
                        "url": link[:1024],
                        "source": source[:128],
                        "published_at": published,
                        "sentiment": sentiment,
                    },
                )
                created += int(was_created)
    return created


def _entry_datetime(entry) -> datetime:
    for key in ("published_parsed", "updated_parsed"):
        parsed = entry.get(key)
        if parsed:
            return datetime(*parsed[:6], tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


def news_features(symbol: str, as_of: datetime, *, exchange: str = "PSX") -> dict[str, float]:
    qs = NewsItem.objects.filter(
        exchange=exchange, symbol=symbol, published_at__lte=as_of
    ).order_by("-published_at")

    win7 = list(qs.filter(published_at__gte=as_of - timedelta(days=7)))
    win30 = list(qs.filter(published_at__gte=as_of - timedelta(days=30)))

    out: dict[str, float] = {
        f"{NAMESPACE}.count_7d": float(len(win7)),
        f"{NAMESPACE}.count_30d": float(len(win30)),
    }

    s7 = [n.sentiment for n in win7 if n.sentiment is not None]
    s30 = [n.sentiment for n in win30 if n.sentiment is not None]
    if s7:
        out[f"{NAMESPACE}.sentiment_mean_7d"] = sum(s7) / len(s7)
    if s30:
        out[f"{NAMESPACE}.sentiment_mean_30d"] = sum(s30) / len(s30)
    if s7 and s30:
        out[f"{NAMESPACE}.sentiment_trend"] = (sum(s7) / len(s7)) - (sum(s30) / len(s30))

    latest_scored = next((n.sentiment for n in win30 if n.sentiment is not None), None)
    if latest_scored is not None:
        out[f"{NAMESPACE}.sentiment_last"] = float(latest_scored)

    return out


@register_feature_provider("news")
class NewsProvider(FeatureProvider):
    namespace = NAMESPACE
    display_name = "News & Headline Sentiment"

    def get_features(self, symbol: str, as_of: datetime, *, exchange: str = "PSX") -> FeatureBundle:
        features = news_features(symbol, as_of, exchange=exchange)
        return FeatureBundle(
            symbol=symbol,
            as_of=as_of,
            exchange=exchange,
            features=features,
            sources=[f"NewsItem rows published <= {as_of:%Y-%m-%d}"],
        )
