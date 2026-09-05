"""Social-media-signal features.

STUB. The `FeatureProvider` interface and the point-in-time query are real;
live ingestion from X / Reddit / StockTwits needs API credentials and
per-platform rate-limit handling and is deferred. `SocialMention` rows are
loaded from a fixture/JSON for now (`load_mentions`). Empty bundle until
rows exist.

Features (windowed to ``posted_at <= as_of``): ``social.mentions_{1,7}d``,
``social.sentiment_mean_7d``, ``social.reach_sum_7d``,
``social.mention_accel`` (1d rate vs 7d daily rate).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from ..models import SocialMention
from .base import FeatureBundle, FeatureProvider, register_feature_provider

logger = logging.getLogger(__name__)

NAMESPACE = "social"


def load_mentions(rows: list[dict], exchange: str = "PSX") -> int:
    """Upsert mentions from dicts with keys: symbol, platform, posted_at
    (ISO), external_id, sentiment, reach. Returns rows created."""
    created = 0
    for row in rows:
        posted_at = row["posted_at"]
        if isinstance(posted_at, str):
            posted_at = datetime.fromisoformat(posted_at)
        _, was_created = SocialMention.objects.get_or_create(
            exchange=exchange,
            symbol=row["symbol"],
            platform=row["platform"],
            external_id=row.get("external_id", ""),
            posted_at=posted_at,
            defaults={
                "sentiment": row.get("sentiment"),
                "reach": int(row.get("reach", 0)),
            },
        )
        created += int(was_created)
    return created


def social_features(symbol: str, as_of: datetime, *, exchange: str = "PSX") -> dict[str, float]:
    qs = SocialMention.objects.filter(exchange=exchange, symbol=symbol, posted_at__lte=as_of)
    win1 = list(qs.filter(posted_at__gte=as_of - timedelta(days=1)))
    win7 = list(qs.filter(posted_at__gte=as_of - timedelta(days=7)))
    if not win7:
        return {}

    out: dict[str, float] = {
        f"{NAMESPACE}.mentions_1d": float(len(win1)),
        f"{NAMESPACE}.mentions_7d": float(len(win7)),
        f"{NAMESPACE}.reach_sum_7d": float(sum(m.reach for m in win7)),
    }
    sent = [m.sentiment for m in win7 if m.sentiment is not None]
    if sent:
        out[f"{NAMESPACE}.sentiment_mean_7d"] = sum(sent) / len(sent)
    daily_rate_7d = len(win7) / 7.0
    if daily_rate_7d > 0:
        out[f"{NAMESPACE}.mention_accel"] = len(win1) / daily_rate_7d
    return out


@register_feature_provider("social")
class SocialProvider(FeatureProvider):
    namespace = NAMESPACE
    display_name = "Social Media Signals (stub - fixture load)"

    def get_features(self, symbol: str, as_of: datetime, *, exchange: str = "PSX") -> FeatureBundle:
        features = social_features(symbol, as_of, exchange=exchange)
        return FeatureBundle(
            symbol=symbol,
            as_of=as_of,
            exchange=exchange,
            features=features,
            sources=["SocialMention rows (fixture load)"],
        )
