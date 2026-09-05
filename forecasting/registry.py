"""Explicit predictor registry; configuration never imports arbitrary code."""

from .base import BasePredictor

_REGISTRY: dict[str, type[BasePredictor]] = {}


def register_predictor(key: str):
    if not isinstance(key, str) or not key.strip():
        raise ValueError("Predictor key must be a nonempty string")

    def decorator(cls: type[BasePredictor]) -> type[BasePredictor]:
        if not issubclass(cls, BasePredictor):
            raise TypeError("Predictors must implement BasePredictor")
        if key in _REGISTRY and _REGISTRY[key] is not cls:
            raise ValueError(f"Predictor key {key!r} is already registered")
        cls.key = key
        _REGISTRY[key] = cls
        return cls

    return decorator


def get_predictor_class(key: str) -> type[BasePredictor]:
    try:
        return _REGISTRY[key]
    except KeyError:
        raise KeyError(
            f"No predictor registered under {key!r}. Known keys: {sorted(_REGISTRY)}"
        ) from None


def registered_keys() -> list[str]:
    return sorted(_REGISTRY)
