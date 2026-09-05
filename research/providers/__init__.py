"""Feature / signal providers.

Every provider implements `FeatureProvider` (see `base.py`) and obeys one
hard rule: it may only use information that was publicly available at or
before the `as_of` timestamp it is given. That point-in-time discipline is
what makes the walk-forward backtester (Phase C) trustworthy - a good
backtest score is only evidence about the future if the features could
actually have been computed in the past.
"""

from .base import (
    FeatureBundle,
    FeatureProvider,
    get_feature_provider,
    register_feature_provider,
    registered_provider_keys,
)

__all__ = [
    "FeatureBundle",
    "FeatureProvider",
    "get_feature_provider",
    "register_feature_provider",
    "registered_provider_keys",
]
