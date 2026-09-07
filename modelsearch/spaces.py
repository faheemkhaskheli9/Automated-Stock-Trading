"""Search-space expansion, validation and scoring helpers.

Deliberately free of Django imports (like ``modeling.features`` /
``modeling.targets``) so ``ModelSearch.clean()`` can call :func:`validate`
cheaply. The only cross-app import is ``modeling.registry`` - which is
scikit-learn-free and already imported by ``modeling.models`` / migrations.

A ``search_space`` is a JSON dict::

    {
      "estimators": ["ridge", "gradient_boosting"],
      "param_grids": {
        "ridge": {"alpha": [0.1, 1.0, 10.0]},
        "gradient_boosting": {"n_estimators": [100, 300], "learning_rate": [0.03, 0.1]}
      }
    }

An estimator listed with no (or an empty) grid contributes exactly one
candidate at its registry defaults.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import random

# Metric keys a search may rank candidates by, per task. ``neg_mae`` / ``neg_rmse``
# are the negated errors so "higher is better" holds for every key.
REGRESSION_SCORES = ("directional_accuracy", "skill_vs_naive", "r2", "neg_mae", "neg_rmse")
CLASSIFICATION_SCORES = ("accuracy", "roc_auc", "f1", "precision", "recall")
DEFAULT_SCORE = {"regression": "directional_accuracy", "classification": "accuracy"}


def valid_scores(task: str) -> tuple[str, ...]:
    return CLASSIFICATION_SCORES if task == "classification" else REGRESSION_SCORES


def params_hash(key: str, params: dict) -> str:
    """Stable hash of an estimator key + its params (order-independent)."""
    payload = json.dumps({"key": key, "params": params or {}}, sort_keys=True, default=str)
    return hashlib.sha1(payload.encode()).hexdigest()


def _grid_candidates(key: str, grid: dict) -> list[tuple[str, dict]]:
    if not grid:
        return [(key, {})]
    names = sorted(grid)
    value_lists = [grid[n] if isinstance(grid[n], list) else [grid[n]] for n in names]
    return [(key, dict(zip(names, combo))) for combo in itertools.product(*value_lists)]


def expand(
    search_space: dict,
    *,
    mode: str = "grid",
    max_candidates: int = 40,
    seed: int = 0,
) -> list[tuple[str, dict]]:
    """Turn a search space into a de-duplicated list of ``(key, params)``.

    ``grid`` keeps the first ``max_candidates`` in expansion order; ``random``
    samples ``max_candidates`` with a seeded RNG (reproducible per search).
    """
    space = search_space or {}
    estimators = space.get("estimators") or []
    grids = space.get("param_grids") or {}

    raw: list[tuple[str, dict]] = []
    for key in estimators:
        raw.extend(_grid_candidates(key, grids.get(key) or {}))

    seen: set[str] = set()
    unique: list[tuple[str, dict]] = []
    for key, params in raw:
        digest = params_hash(key, params)
        if digest in seen:
            continue
        seen.add(digest)
        unique.append((key, params))

    if len(unique) <= max_candidates:
        return unique
    if mode == "random":
        return random.Random(seed).sample(unique, max_candidates)
    return unique[:max_candidates]


def scalar_score(metrics: dict, key: str):
    """Pull the ranking scalar out of a metrics blob ('higher is better')."""
    if not metrics:
        return None
    if key == "neg_mae":
        value = metrics.get("mae")
        return None if value is None else -value
    if key == "neg_rmse":
        value = metrics.get("rmse")
        return None if value is None else -value
    return metrics.get(key)


def validate(search_space, *, task: str) -> None:
    """Raise ``ValueError`` if the space is malformed or task-incompatible."""
    from modeling.registry import get_estimator

    if not isinstance(search_space, dict):
        raise ValueError("search_space must be a JSON object")
    estimators = search_space.get("estimators")
    if not isinstance(estimators, list) or not estimators:
        raise ValueError("search_space.estimators must be a non-empty list of estimator keys")
    grids = search_space.get("param_grids", {})
    if not isinstance(grids, dict):
        raise ValueError("search_space.param_grids must be an object keyed by estimator key")

    stray = set(grids) - set(estimators)
    if stray:
        raise ValueError(f"param_grids has keys not in estimators: {sorted(stray)}")

    for key in estimators:
        try:
            spec = get_estimator(key)
        except KeyError as exc:
            raise ValueError(str(exc)) from None
        if not spec.available:
            raise ValueError(f"estimator {key!r} is not available in this environment")
        if spec.task != task:
            raise ValueError(
                f"estimator {key!r} is a {spec.task} model, but the target is a {task} problem"
            )
        grid = grids.get(key) or {}
        if not isinstance(grid, dict):
            raise ValueError(f"param_grids[{key!r}] must be an object of param -> list of values")
        for pname, values in grid.items():
            vlist = values if isinstance(values, list) else [values]
            if not vlist:
                raise ValueError(f"param_grids[{key!r}][{pname!r}] is an empty list")
            for value in vlist:
                try:
                    spec.coerce_params({pname: value})
                except ValueError as exc:
                    raise ValueError(f"{key}.{pname}={value!r}: {exc}") from None
