"""Strategy classes register themselves under a short string key.

The `Strategy` model (below) stores that key rather than a dotted import
path, so configuring a strategy instance from the admin never involves
typing/trusting an arbitrary Python path.
"""

from .base import BaseStrategy

_REGISTRY: dict[str, type[BaseStrategy]] = {}


def register_strategy(key: str):
    def decorator(cls: type[BaseStrategy]) -> type[BaseStrategy]:
        if key in _REGISTRY and _REGISTRY[key] is not cls:
            raise ValueError(f"Strategy key {key!r} is already registered to {_REGISTRY[key]!r}")
        cls.key = key
        _REGISTRY[key] = cls
        return cls

    return decorator


def get_strategy_class(key: str) -> type[BaseStrategy]:
    try:
        return _REGISTRY[key]
    except KeyError:
        raise KeyError(
            f"No strategy registered under key {key!r}. Known keys: {sorted(_REGISTRY)}"
        ) from None


def registered_keys() -> list[str]:
    return sorted(_REGISTRY)


def registry_choices() -> list[tuple[str, str]]:
    """(key, display_name) pairs for use as a Django model field's `choices`."""
    return [(key, cls.display_name or key) for key, cls in sorted(_REGISTRY.items())]
