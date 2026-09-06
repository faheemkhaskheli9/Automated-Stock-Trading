"""Estimator classes register themselves under a short string key.

`TradingModel.estimator_key` stores that key rather than a dotted import
path, so a model configured from the UI or admin never involves typing or
trusting an arbitrary Python path. Mirrors ``strategies/registry.py`` and
``forecasting/registry.py``.
"""

from .estimators_base import BaseEstimatorSpec

_REGISTRY: dict[str, type[BaseEstimatorSpec]] = {}


def register_estimator(key: str):
    if not isinstance(key, str) or not key.strip():
        raise ValueError("Estimator key must be a nonempty string")

    def decorator(cls: type[BaseEstimatorSpec]) -> type[BaseEstimatorSpec]:
        if not issubclass(cls, BaseEstimatorSpec):
            raise TypeError("Estimators must implement BaseEstimatorSpec")
        if key in _REGISTRY and _REGISTRY[key] is not cls:
            raise ValueError(f"Estimator key {key!r} is already registered")
        cls.key = key
        _REGISTRY[key] = cls
        return cls

    return decorator


def get_estimator(key: str) -> type[BaseEstimatorSpec]:
    try:
        return _REGISTRY[key]
    except KeyError:
        raise KeyError(
            f"No estimator registered under {key!r}. Known keys: {sorted(_REGISTRY)}"
        ) from None


def registered_keys() -> list[str]:
    return sorted(_REGISTRY)


def registry_choices(*, include_unavailable: bool = True) -> list[tuple[str, str]]:
    """``(key, label)`` pairs for a Django ``ChoiceField``.

    The label carries the task and an "(unavailable)" marker so the picker
    is self-describing without JavaScript.
    """
    choices = []
    for key, cls in sorted(_REGISTRY.items()):
        if not cls.available and not include_unavailable:
            continue
        label = f"{cls.display_name or key} - {cls.task}"
        if not cls.available:
            label += " (unavailable)"
        choices.append((key, label))
    return choices


def catalogue() -> list[dict]:
    """Full registry snapshot for the read-only estimators page."""
    return [
        {
            "key": key,
            "display_name": cls.display_name or key,
            "task": cls.task,
            "available": cls.available,
            "needs_scaling": cls.needs_scaling,
            "multioutput": cls.multioutput,
            "param_schema": {
                name: {"type": typ.__name__, "default": default}
                for name, (typ, default) in cls.param_schema.items()
            },
        }
        for key, cls in sorted(_REGISTRY.items())
    ]
