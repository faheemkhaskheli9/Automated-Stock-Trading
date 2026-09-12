---
name: add-forecasting-predictor
description: Add a new next-day-close predictor to the leakage-strict forecasting app (naive/drift/sarima/ets/ridge/elasticnet/gradient_boosting/lstm already exist). Use when asked to add a forecasting model, predictor, or algorithm to the strict walk-forward path (not the modeling studio).
---

# Add a forecasting predictor

`forecasting` (see `docs/FORECASTING.md`, KB `forecasting-layer.md`) is the
**leakage-strict** next-day-close path — deliberately separate from the
UI-driven `modeling` studio (that one has its own skill:
`add-modeling-estimator`). Use this skill only when the ask is specifically
about the strict path / `forecasting/backtesting/` walk-forward runner.

## Steps

1. **New module** under `forecasting/` (mirror `linear.py`/`trees.py` for a
   plain sklearn-style fit, or `deep.py` for an optional-dependency model —
   `lstm` there is soft-imported from `requirements-ml.txt`'s `torch` and
   simply doesn't register when it's absent; follow that guard exactly for
   any new heavy dependency).
2. **Two families of base class**:
   - A frame model (row-independent, full point-in-time feature frame): 
     subclass `forecasting/_frame_model.py::FrameModelPredictor` — this is
     what `ridge`/`elasticnet`/`gradient_boosting`/`lstm` all do. You get
     the imputer/scaler pipeline, feature-schema pinning, and row-wise
     prediction for free; only implement the estimator itself.
   - A classic time-series model needing prefix replay (like
     `sarima`/`ets`): implement `BasePredictor` directly
     (`forecasting/base.py`) with `fit`/`predict_next`/`predict_series`,
     training-only parameter fits, and reject inference before the latest
     training label was available (mirror `forecasting/stats.py`... check
     the actual module name for the current sarima/ets implementation
     before copying).
3. **Register**: `@register_predictor("key")`
   (`forecasting/registry.py`), imported from `forecasting/apps.py::ready()`.
4. **Respect the point-in-time contract**: never read a bar or a feature
   dated after the frame's `end`/`as_of`; daily bars and date-only
   fundamental releases become usable at the *next local midnight*, same
   convention as `research`. `predict_next` must require an explicit target
   session date — never guess holidays or peek at future bars.
5. **Tests**: a fit/predict round-trip test (`predict_series` length matches
   input), plus — if the model has any internal state carried across calls —
   a leak canary proving it refuses inference before its latest training
   label was available (see the `drift` predictor's existing test for the
   pattern).
6. **Walk-forward**: no separate wiring needed — once registered, the
   predictor is selectable from `/forecast-backtests/`
   (`forecasting/backtesting/` + `backtest_predictor` command) and scorable
   via `forecasting.services.run_forecast_backtest`.
7. **Docs**: add it to the predictor list in `docs/FORECASTING.md`.

## Verify

```
.venv/Scripts/python.exe -m pytest forecasting -q
python manage.py backtest_predictor SYMBOL your_key --start 2024-01-01 --end 2024-06-01
```

If `looks_leaky` comes back true on a `ForecastBacktestRun`, stop and fix the
predictor before treating its numbers as real.
