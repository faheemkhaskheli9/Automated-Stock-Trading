"""Concrete estimator specs: scikit-learn models + trivial baselines.

Imported from ``modeling.apps.ModelingConfig.ready``; importing scikit-learn
here (rather than in ``registry.py`` / ``models.py``) keeps migrations and
model imports light.
"""

from __future__ import annotations

import numpy as np
from sklearn.base import BaseEstimator, RegressorMixin
from sklearn.ensemble import (
    GradientBoostingClassifier,
    GradientBoostingRegressor,
    HistGradientBoostingClassifier,
    HistGradientBoostingRegressor,
    RandomForestClassifier,
    RandomForestRegressor,
)
from sklearn.linear_model import (
    ElasticNet,
    Lasso,
    LinearRegression,
    LogisticRegression,
    Ridge,
)
from sklearn.neural_network import MLPClassifier, MLPRegressor

from .estimators_base import TASK_CLASSIFICATION, TASK_REGRESSION, BaseEstimatorSpec
from .registry import register_estimator

# Anchor feature every baseline reads (the close of the decision bar).
CLOSE_NOW = "ohlc.close_lag_0"


# --------------------------------------------------------------------------
# Baseline estimators - sklearn-compatible, read a single input column.
# training.py resolves the column position and injects it as anchor_index.
# --------------------------------------------------------------------------
class _NaiveLast(BaseEstimator, RegressorMixin):
    def __init__(self, anchor_index: int = 0):
        self.anchor_index = anchor_index

    def fit(self, X, y=None):
        self.n_features_in_ = np.asarray(X, dtype=float).shape[1]
        return self

    def predict(self, X):
        return np.asarray(X, dtype=float)[:, self.anchor_index]


class _Drift(_NaiveLast):
    def fit(self, X, y):
        super().fit(X, y)
        anchor = np.asarray(X, dtype=float)[:, self.anchor_index]
        self.offset_ = float(np.mean(np.asarray(y, dtype=float) - anchor))
        return self

    def predict(self, X):
        return super().predict(X) + self.offset_


def _mlp_layers(spec: str) -> tuple[int, ...]:
    try:
        layers = tuple(int(part) for part in str(spec).split(",") if part.strip())
    except ValueError as exc:
        raise ValueError(f"hidden_layers must be comma-separated ints, got {spec!r}") from exc
    if not layers or any(n <= 0 for n in layers):
        raise ValueError("hidden_layers must be one or more positive ints")
    return layers


def _depth(value) -> int | None:
    """0 (the form default) means 'no limit'."""
    return None if not value else int(value)


# --------------------------------------------------------------------------
# Spec table. Each entry becomes a registered BaseEstimatorSpec subclass.
# --------------------------------------------------------------------------
_SPECS: list[dict] = [
    # -- linear ----------------------------------------------------------
    dict(
        key="linear",
        name="Linear regression",
        task=TASK_REGRESSION,
        scale=True,
        multioutput=True,
        schema={},
        make=lambda p: LinearRegression(),
    ),
    dict(
        key="ridge",
        name="Ridge regression",
        task=TASK_REGRESSION,
        scale=True,
        multioutput=True,
        schema={"alpha": (float, 1.0)},
        make=lambda p: Ridge(alpha=p["alpha"]),
    ),
    dict(
        key="lasso",
        name="Lasso regression",
        task=TASK_REGRESSION,
        scale=True,
        multioutput=False,
        schema={"alpha": (float, 0.1)},
        make=lambda p: Lasso(alpha=p["alpha"], max_iter=10_000),
    ),
    dict(
        key="elasticnet",
        name="ElasticNet regression",
        task=TASK_REGRESSION,
        scale=True,
        multioutput=False,
        schema={"alpha": (float, 0.1), "l1_ratio": (float, 0.5)},
        make=lambda p: ElasticNet(alpha=p["alpha"], l1_ratio=p["l1_ratio"], max_iter=10_000),
    ),
    dict(
        key="logistic",
        name="Logistic regression",
        task=TASK_CLASSIFICATION,
        scale=True,
        multioutput=False,
        schema={"C": (float, 1.0), "max_iter": (int, 1000)},
        make=lambda p: LogisticRegression(C=p["C"], max_iter=p["max_iter"]),
    ),
    # -- trees / ensembles --------------------------------------------------
    dict(
        key="random_forest",
        name="Random forest regressor",
        task=TASK_REGRESSION,
        scale=False,
        multioutput=True,
        schema={"n_estimators": (int, 200), "max_depth": (int, 0)},
        make=lambda p: RandomForestRegressor(
            n_estimators=p["n_estimators"],
            max_depth=_depth(p["max_depth"]),
            random_state=0,
            n_jobs=-1,
        ),
    ),
    dict(
        key="random_forest_clf",
        name="Random forest classifier",
        task=TASK_CLASSIFICATION,
        scale=False,
        multioutput=False,
        schema={"n_estimators": (int, 200), "max_depth": (int, 0)},
        make=lambda p: RandomForestClassifier(
            n_estimators=p["n_estimators"],
            max_depth=_depth(p["max_depth"]),
            random_state=0,
            n_jobs=-1,
        ),
    ),
    dict(
        key="gradient_boosting",
        name="Gradient boosting regressor",
        task=TASK_REGRESSION,
        scale=False,
        multioutput=False,
        schema={"n_estimators": (int, 200), "learning_rate": (float, 0.05), "max_depth": (int, 3)},
        make=lambda p: GradientBoostingRegressor(
            n_estimators=p["n_estimators"],
            learning_rate=p["learning_rate"],
            max_depth=p["max_depth"],
            random_state=0,
        ),
    ),
    dict(
        key="gradient_boosting_clf",
        name="Gradient boosting classifier",
        task=TASK_CLASSIFICATION,
        scale=False,
        multioutput=False,
        schema={"n_estimators": (int, 200), "learning_rate": (float, 0.05), "max_depth": (int, 3)},
        make=lambda p: GradientBoostingClassifier(
            n_estimators=p["n_estimators"],
            learning_rate=p["learning_rate"],
            max_depth=p["max_depth"],
            random_state=0,
        ),
    ),
    dict(
        key="hist_gbr",
        name="Hist gradient boosting regressor",
        task=TASK_REGRESSION,
        scale=False,
        multioutput=False,
        schema={"max_iter": (int, 300), "learning_rate": (float, 0.05)},
        make=lambda p: HistGradientBoostingRegressor(
            max_iter=p["max_iter"],
            learning_rate=p["learning_rate"],
            random_state=0,
        ),
    ),
    dict(
        key="hist_gbr_clf",
        name="Hist gradient boosting classifier",
        task=TASK_CLASSIFICATION,
        scale=False,
        multioutput=False,
        schema={"max_iter": (int, 300), "learning_rate": (float, 0.05)},
        make=lambda p: HistGradientBoostingClassifier(
            max_iter=p["max_iter"],
            learning_rate=p["learning_rate"],
            random_state=0,
        ),
    ),
    # -- neural nets (sklearn - no torch) --------------------------------
    dict(
        key="mlp",
        name="MLP regressor",
        task=TASK_REGRESSION,
        scale=True,
        multioutput=True,
        schema={"hidden_layers": (str, "64,32"), "alpha": (float, 1e-4), "max_iter": (int, 500)},
        make=lambda p: MLPRegressor(
            hidden_layer_sizes=_mlp_layers(p["hidden_layers"]),
            alpha=p["alpha"],
            max_iter=p["max_iter"],
            random_state=0,
        ),
    ),
    dict(
        key="mlp_clf",
        name="MLP classifier",
        task=TASK_CLASSIFICATION,
        scale=True,
        multioutput=False,
        schema={"hidden_layers": (str, "64,32"), "alpha": (float, 1e-4), "max_iter": (int, 500)},
        make=lambda p: MLPClassifier(
            hidden_layer_sizes=_mlp_layers(p["hidden_layers"]),
            alpha=p["alpha"],
            max_iter=p["max_iter"],
            random_state=0,
        ),
    ),
    # -- baselines ------------------------------------------------------
    dict(
        key="naive_last",
        name="Naive (last close)",
        task=TASK_REGRESSION,
        scale=False,
        multioutput=False,
        baseline=True,
        anchor=CLOSE_NOW,
        schema={},
        make=lambda p: _NaiveLast(),
    ),
    dict(
        key="drift",
        name="Drift (last close + mean change)",
        task=TASK_REGRESSION,
        scale=False,
        multioutput=False,
        baseline=True,
        anchor=CLOSE_NOW,
        schema={},
        make=lambda p: _Drift(),
    ),
    dict(
        key="seasonal_naive",
        name="Seasonal naive (lagged close)",
        task=TASK_REGRESSION,
        scale=False,
        multioutput=False,
        baseline=True,
        anchor=None,
        schema={"season": (int, 5)},
        make=lambda p: _NaiveLast(),
        anchor_fn=lambda p: f"ohlc.close_lag_{int(p['season'])}",
    ),
]


def _build_spec(entry: dict) -> type[BaseEstimatorSpec]:
    _make = entry["make"]
    _anchor_fn = entry.get("anchor_fn")
    _fixed_anchor = entry.get("anchor")

    class _Spec(BaseEstimatorSpec):
        display_name = entry["name"]
        task = entry["task"]
        needs_scaling = entry["scale"]
        multioutput = entry["multioutput"]
        baseline = entry.get("baseline", False)
        param_schema = entry["schema"]

        @classmethod
        def make(cls, params: dict):
            return _make(params)

        @classmethod
        def anchor_feature(cls, params: dict | None = None) -> str | None:
            if _anchor_fn is not None:
                return _anchor_fn(cls.coerce_params(params))
            return _fixed_anchor

    _Spec.__name__ = _Spec.__qualname__ = f"{entry['key'].title().replace('_', '')}Spec"
    return register_estimator(entry["key"])(_Spec)


for _entry in _SPECS:
    _build_spec(_entry)
