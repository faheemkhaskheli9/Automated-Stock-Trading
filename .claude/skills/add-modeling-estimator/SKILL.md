---
name: add-modeling-estimator
description: Register a new estimator (sklearn model, ensemble, or custom predictor) in the modeling app's registry so it shows up in TradingModel/ModelSearch pickers. Use when asked to add a new model type, algorithm, or predictor to the modeling studio.
---

# Add a modeling estimator

`modeling` (the configurable-model studio, see `docs/MODELING.md` and the
`automated-stock-trading` project KB's `modeling-app.md`) drives everything
off a string-keyed registry in `modeling/registry.py`. Follow this exact
shape — the UI, `TradingModel.clean()`, and `modelsearch`'s validation all
depend on it.

## Steps

1. **Add the spec entry.** Open `modeling/estimators.py` (sklearn-backed
   models) or `modeling/deep.py` (torch-backed, soft-imported — mirror its
   `try/except ImportError` + `available = False` fallback pattern if the
   new estimator needs an optional heavy dependency). Add one dict to the
   `_SPECS` list:
   ```python
   dict(
       key="my_key",                      # short, stable, stored in the DB
       name="Human-readable name",
       task=TASK_REGRESSION,              # or TASK_CLASSIFICATION
       scale=True,                        # True if the estimator wants a StandardScaler
       multioutput=False,                 # True only if it natively handles 2-D y (multistep target)
       schema={"param": (float, 1.0)},    # {name: (python_type, default)} — drives the UI form + coercion
       make=lambda p: SomeSklearnClass(param=p["param"]),
   )
   ```
   `_build_spec()` wraps each dict into a `BaseEstimatorSpec` subclass and
   calls `register_estimator(key)` automatically — you don't write the
   registration boilerplate by hand.
2. **If it needs another already-registered estimator** (an ensemble/meta
   model, like `voting_ensemble`), resolve sub-estimator keys **lazily**
   inside `make`/a helper function via `from .registry import get_estimator`
   — not at module import time — since `_SPECS` entries register in file
   order and a forward reference would fail. See `_build_voting_ensemble` in
   `modeling/estimators.py` for the pattern (per-sub-estimator scaling,
   rejecting baselines/classifiers/self-reference).
3. **Baselines** (a trivial reference model reading one input column, like
   `naive_last`) additionally set `baseline=True` and either a fixed
   `anchor="ohlc.close_lag_0"` or an `anchor_fn=lambda p: f"..."` — see the
   `-- baselines --` section of `_SPECS`.
4. **Tests** — `modeling/tests/test_estimators.py` already parametrizes
   `test_available_estimator_builds` over every registered key except
   `lstm`, so a correctly-registered estimator is covered for free. Add
   estimator-specific tests (param validation, a fit/predict sanity check)
   alongside the existing ones, following their style.
5. **Docs** — add a line to the `## Estimators` section of
   `docs/MODELING.md`.
6. Optional dependency? Add it to `requirements-ml.txt` (not
   `requirements.txt`) and guard the import, matching `modeling/deep.py`'s
   `lstm` pattern so the app still starts without it.

## Verify

```
.venv/Scripts/python.exe -m pytest modeling modelsearch -q
```

An estimator registered here is immediately selectable from `/modeling/`
(`TradingModel.estimator_key`) and from `/model-search/` (`ModelSearch`'s
`search_space.estimators` list) with no other wiring.
