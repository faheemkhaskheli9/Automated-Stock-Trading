"""Base class for registered estimator specs.

Kept in its own module (not ``estimators.py``) so ``registry.py`` can import
it without pulling in scikit-learn or the concrete estimator classes - the
registry is imported by ``models.py``/migrations, which must stay import-light.
"""

from __future__ import annotations

from typing import Any

TASK_REGRESSION = "regression"
TASK_CLASSIFICATION = "classification"


class BaseEstimatorSpec:
    """Describes one selectable model type.

    Subclasses set the class attributes and implement :meth:`make`. They are
    never instantiated - :meth:`build` is a classmethod returning a fresh
    scikit-learn-compatible estimator each call.
    """

    #: Registry key, set by @register_estimator.
    key: str = ""
    #: Human-readable name for the picker / catalogue.
    display_name: str = ""
    #: "regression" or "classification".
    task: str = TASK_REGRESSION
    #: Whether a StandardScaler should precede this estimator in the pipeline.
    needs_scaling: bool = False
    #: False if a required optional dependency (e.g. torch) is missing.
    available: bool = True
    #: True if the raw estimator handles a 2-D ``y`` (multi-step targets)
    #: without a MultiOutputRegressor wrapper.
    multioutput: bool = False
    #: True for trivial reference models that read one input column; training
    #: resolves that column via :meth:`anchor_feature` and injects its index.
    baseline: bool = False
    #: ``{param_name: (python_type, default)}`` - drives form fields and
    #: coercion. Only these keys are accepted from user-supplied params.
    param_schema: dict[str, tuple[type, Any]] = {}

    @classmethod
    def coerce_params(cls, params: dict | None) -> dict:
        """Validate ``params`` against ``param_schema``; return coerced copy."""
        params = dict(params or {})
        unknown = set(params) - set(cls.param_schema)
        if unknown:
            raise ValueError(
                f"{cls.key!r} got unknown params {sorted(unknown)}; "
                f"accepted: {sorted(cls.param_schema)}"
            )
        coerced: dict[str, Any] = {}
        for name, (typ, default) in cls.param_schema.items():
            value = params.get(name, default)
            if value is None:
                coerced[name] = None
                continue
            try:
                coerced[name] = typ(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"{cls.key!r} param {name!r} must be {typ.__name__}, got {value!r}"
                ) from exc
        return coerced

    @classmethod
    def build(cls, **params):
        """Return a fresh estimator configured with (coerced) ``params``."""
        return cls.make(cls.coerce_params(params))

    @classmethod
    def make(cls, params: dict):  # pragma: no cover - abstract
        raise NotImplementedError

    @classmethod
    def anchor_feature(cls, params: dict | None = None) -> str | None:
        """Feature column a baseline estimator reads (None for real models)."""
        return None
