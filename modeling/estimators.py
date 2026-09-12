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
    StackingRegressor,
    VotingRegressor,
)
from sklearn.linear_model import (
    ElasticNet,
    Lasso,
    LinearRegression,
    LogisticRegression,
    Ridge,
)
from sklearn.neural_network import MLPClassifier, MLPRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

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


def _resolve_ensemble_members(ensemble_key: str, estimators_param) -> list[tuple[str, object]]:
    """Shared member-resolution for the meta-estimators below.

    Sub-estimator keys are resolved lazily (at ``.make()``/training time, not
    at module-import time) via the registry, so ordering in ``_SPECS`` below
    doesn't matter - every other spec is registered before any model is
    actually trained. Each sub-estimator gets its own ``StandardScaler`` iff
    it needs one, since a meta-estimator has no single scaling policy that
    would suit both a linear model and a tree ensemble at once.
    """
    # Local import: avoids a module-level cycle with registry.py at import time.
    from .registry import get_estimator

    keys = [k.strip() for k in str(estimators_param).split(",") if k.strip()]
    seen = set()
    keys = [k for k in keys if not (k in seen or seen.add(k))]
    if len(keys) < 2:
        raise ValueError(
            f"{ensemble_key} needs at least 2 distinct, comma-separated estimator keys "
            f"(got {estimators_param!r})"
        )
    members = []
    for key in keys:
        if key == ensemble_key:
            raise ValueError(f"{ensemble_key} cannot include itself as a sub-estimator")
        spec = get_estimator(key)
        if spec.task != TASK_REGRESSION or spec.baseline:
            raise ValueError(
                f"{ensemble_key}: {key!r} is not a usable regression sub-estimator "
                "(must be a non-baseline regressor)"
            )
        estimator = spec.build()
        if spec.needs_scaling:
            estimator = make_pipeline(StandardScaler(), estimator)
        members.append((key, estimator))
    return members


def _build_voting_ensemble(params: dict) -> VotingRegressor:
    """Average several already-registered regressors into one estimator."""
    members = _resolve_ensemble_members("voting_ensemble", params["estimators"])
    return VotingRegressor(estimators=members)


def _build_stacking_ensemble(params: dict) -> StackingRegressor:
    """Stack several already-registered regressors behind a meta-learner.

    Same registry-lazy member resolution as ``voting_ensemble``, plus a
    ``final_estimator`` (also a registry key, default ``ridge``) trained on
    the base models' out-of-fold predictions - ``StackingRegressor.fit`` runs
    its own internal ``cv``-fold split on the training data it is given, so
    this stays leak-free under ``backtesting``'s per-fold refit the same way
    any other estimator does (fit only ever sees that fold's training rows).
    """
    from .registry import get_estimator

    members = _resolve_ensemble_members("stacking_ensemble", params["estimators"])

    final_key = params["final_estimator"]
    if final_key == "stacking_ensemble":
        raise ValueError("stacking_ensemble cannot use itself as the final_estimator")
    final_spec = get_estimator(final_key)
    if final_spec.task != TASK_REGRESSION or final_spec.baseline:
        raise ValueError(
            f"stacking_ensemble: final_estimator {final_key!r} is not a usable regression "
            "estimator (must be a non-baseline regressor)"
        )
    final_estimator = final_spec.build()
    if final_spec.needs_scaling:
        final_estimator = make_pipeline(StandardScaler(), final_estimator)

    cv = params["cv"]
    if cv < 2:
        raise ValueError(f"stacking_ensemble: cv must be at least 2 (got {cv})")

    return StackingRegressor(estimators=members, final_estimator=final_estimator, cv=cv)


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
    # -- ensembles-of-estimators ------------------------------------------
    dict(
        key="voting_ensemble",
        name="Voting ensemble (average of several regressors)",
        task=TASK_REGRESSION,
        scale=False,
        multioutput=False,
        schema={"estimators": (str, "ridge,gradient_boosting,hist_gbr")},
        make=lambda p: _build_voting_ensemble(p),
    ),
    dict(
        key="stacking_ensemble",
        name="Stacking ensemble (meta-learner over several regressors)",
        task=TASK_REGRESSION,
        scale=False,
        multioutput=False,
        schema={
            "estimators": (str, "ridge,gradient_boosting,hist_gbr"),
            "final_estimator": (str, "ridge"),
            "cv": (int, 5),
        },
        make=lambda p: _build_stacking_ensemble(p),
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
