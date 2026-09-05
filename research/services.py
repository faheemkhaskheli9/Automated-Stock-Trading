"""Assemble and cache point-in-time feature bundles.

`build_feature_bundle` runs every registered `FeatureProvider` for one
(symbol, as_of) and merges the results. `get_or_build_snapshot` persists
that as a `ResearchSnapshot` so the forecasting layer (Phase B) and the
walk-forward backtester (Phase C) read frozen, reproducible inputs.
"""

from __future__ import annotations

import logging
from datetime import datetime

from .models import ResearchSnapshot
from .providers.base import FeatureBundle, get_feature_provider, registered_provider_keys

logger = logging.getLogger(__name__)

# Order is cosmetic (features are namespaced); keep technical first so a
# bundle always leads with price-derived features.
DEFAULT_PROVIDER_KEYS = ["technical", "news", "fundamentals", "social"]


def _provider_keys(keys: list[str] | None) -> list[str]:
    if keys is not None:
        return keys
    registered = registered_provider_keys()
    ordered = [k for k in DEFAULT_PROVIDER_KEYS if k in registered]
    return ordered + [k for k in registered if k not in ordered]


def build_feature_bundle(
    symbol: str,
    as_of: datetime,
    *,
    exchange: str = "PSX",
    provider_keys: list[str] | None = None,
) -> FeatureBundle:
    """Merged `FeatureBundle` from every requested provider. A provider that
    raises is logged and skipped - assembly never fails because one thin
    signal source is broken."""
    bundle = FeatureBundle(symbol=symbol, as_of=as_of, exchange=exchange)
    for key in _provider_keys(provider_keys):
        try:
            provider = get_feature_provider(key)()
            bundle = bundle.merge(provider.get_features(symbol, as_of, exchange=exchange))
        except Exception:
            logger.exception("Feature provider %r failed for %s @ %s", key, symbol, as_of)
    return bundle


def get_or_build_snapshot(
    symbol: str,
    as_of: datetime,
    *,
    exchange: str = "PSX",
    provider_keys: list[str] | None = None,
    rebuild: bool = False,
) -> ResearchSnapshot:
    keys = _provider_keys(provider_keys)
    if not rebuild:
        existing = ResearchSnapshot.objects.filter(
            exchange=exchange, symbol=symbol, as_of=as_of
        ).first()
        if existing is not None:
            return existing

    bundle = build_feature_bundle(symbol, as_of, exchange=exchange, provider_keys=keys)
    snapshot, _ = ResearchSnapshot.objects.update_or_create(
        exchange=exchange,
        symbol=symbol,
        as_of=as_of,
        defaults={
            "features": bundle.features,
            "sources": bundle.sources,
            "provider_keys": keys,
        },
    )
    return snapshot
