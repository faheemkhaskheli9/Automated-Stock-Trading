"""The one interface every feature/signal source implements.

`FeatureProvider.get_features(symbol, as_of, ...)` returns a flat
``{name: float}`` map of features for one instrument, computed **only** from
information available at or before ``as_of``. Downstream code (the
forecasting feature assembler in Phase B, the walk-forward backtester in
Phase C) depends on this interface and the registry below - never on a
concrete provider class.

Naming convention: every feature key is ``"<namespace>.<name>"`` (e.g.
``"technical.rsi_14"``, ``"news.sentiment_mean_7d"``) so merged bundles
never collide and the UI can group them.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class FeatureBundle:
    """A point-in-time feature snapshot for one instrument.

    ``features`` is a flat float map; ``sources`` lists human-readable
    citations (feed names, file paths, "PriceBar history") so a bundle is
    self-describing and a stored snapshot stays auditable.
    """

    symbol: str
    as_of: datetime
    exchange: str = "PSX"
    features: dict[str, float] = field(default_factory=dict)
    sources: list[str] = field(default_factory=list)

    def merge(self, other: "FeatureBundle") -> "FeatureBundle":
        if other.symbol != self.symbol or other.exchange != self.exchange:
            raise ValueError("Cannot merge feature bundles for different instruments")
        merged = dict(self.features)
        overlap = merged.keys() & other.features.keys()
        if overlap:
            raise ValueError(f"Feature key collision while merging bundles: {sorted(overlap)}")
        merged.update(other.features)
        return FeatureBundle(
            symbol=self.symbol,
            as_of=max(self.as_of, other.as_of),
            exchange=self.exchange,
            features=merged,
            sources=[*self.sources, *other.sources],
        )


class FeatureProvider(ABC):
    """Interface every feature source (technical, news, fundamentals,
    social, ...) must implement."""

    #: Registry key, set by @register_feature_provider.
    key: str = ""
    #: Feature-name namespace this provider owns, e.g. "technical".
    namespace: str = ""
    #: Human-readable name for the UI.
    display_name: str = ""

    @abstractmethod
    def get_features(self, symbol: str, as_of: datetime, *, exchange: str = "PSX") -> FeatureBundle:
        """Return a `FeatureBundle` for ``symbol`` as of ``as_of``.

        MUST NOT read any bar, headline, post, or report dated after
        ``as_of``. MUST return a bundle (possibly with an empty
        ``features`` map) rather than raising when data is missing, so one
        thin provider never breaks the whole assembly.
        """


_REGISTRY: dict[str, type[FeatureProvider]] = {}


def register_feature_provider(key: str):
    def decorator(cls: type[FeatureProvider]) -> type[FeatureProvider]:
        if key in _REGISTRY and _REGISTRY[key] is not cls:
            raise ValueError(
                f"Feature provider key {key!r} already registered to {_REGISTRY[key]!r}"
            )
        cls.key = key
        _REGISTRY[key] = cls
        return cls

    return decorator


def get_feature_provider(key: str) -> type[FeatureProvider]:
    try:
        return _REGISTRY[key]
    except KeyError:
        raise KeyError(
            f"No feature provider registered under {key!r}. Known: {sorted(_REGISTRY)}"
        ) from None


def registered_provider_keys() -> list[str]:
    return sorted(_REGISTRY)
