# `modeling` app - configurable trading-model studio

Lets an operator define a model as data - **an estimator + an input
(feature) spec + an output (target) spec** - train it, and use it for
prediction. It sits alongside the strict `forecasting` app (next-day close
only); `modeling` is the flexible, UI-driven path.

Pages (all `login_required`, routed under `/modeling/`):

| URL | Purpose |
|---|---|
| `/modeling/` | List models + headline holdout metric |
| `/modeling/new/`, `/modeling/<id>/edit/` | Configure a model |
| `/modeling/<id>/` | Config, metrics (train vs holdout), run history, **Train now**, recent predictions, predicted-vs-actual chart, predictions CSV |
| `/modeling/<id>/predict/` | Run the trained model for one instrument / date |
| `/modeling/estimators/` | Read-only estimator catalogue |
| `/modeling/leaderboard/` | Active models ranked by rolling accuracy (`?window=30\|90\|180\|365` days) |

### Accuracy leaderboard

`/modeling/leaderboard/` (`modeling/leaderboard.py::build_leaderboard`) scores
every **active** `TradingModel` over a trailing window of its backfilled
`ModelPrediction` rows (only predictions whose target session has closed and
been through `backfill_actuals` count):

- **MAE** - mean `abs_error`, in the target's own units; `None` for the
  `direction` classifier.
- **Directional accuracy** - share of predictions that called the move (up vs
  down) correctly against the last close known at decision time (`as_of`); for
  `direction` targets this is plain accuracy.
- **Skill** - `1 - model_mae / naive_mae` for regression targets (beats the
  naive "no change" forecast when `> 0`), or
  `(accuracy - majority_rate) / (1 - majority_rate)` for the classifier.

Ranking is by skill (models with no computable skill sort last), tie-broken by
directional accuracy. MAE is shown but never ranked on - it is not comparable
across targets on different scales. Active models with no scored predictions in
the window are listed separately as "unranked".

## Estimators

Registered under short keys (`modeling/estimators.py`, `modeling/deep.py`);
see `/modeling/estimators/` for the live list and each one's params.

- **Linear** (`sklearn.linear_model`): `linear`, `ridge`, `lasso`,
  `elasticnet`, `logistic` (classification).
- **Trees / ensembles** (`sklearn.ensemble`): `random_forest`(+`_clf`),
  `gradient_boosting`(+`_clf`), `hist_gbr`(+`_clf`).
- **Neural net** (`sklearn.neural_network`, no torch): `mlp` / `mlp_clf`.
- **Baselines**: `naive_last`, `drift`, `seasonal_naive` - trivial
  references for the skill-vs-naive number. They read one input column and
  therefore need an `ohlc` source with the matching close lag in the
  feature spec (`naive_last`/`drift` -> lag 0; `seasonal_naive` -> lag
  `season`).
- **`lstm`** (PyTorch): optional. Install `requirements-ml.txt` to enable
  it; otherwise it shows as *unavailable* and is rejected on save.

An estimator's `task` must match the target's task (regression vs
classification) - enforced in `TradingModel.clean()`.

## Feature spec

A JSON **list** of source descriptors (`modeling/features.py`). Every source
is computed **as of each decision timestamp** using only the price prefix up
to that bar - no look-ahead. Missing warmups stay NaN and are median-imputed
inside the training pipeline (fit on training rows only).

| kind | params | columns |
|---|---|---|
| `ohlc` | `fields`, `lags` (0 = decision bar) | `ohlc.<field>_lag_<k>` |
| `return` | `periods` | `return.<p>` |
| `technical` | `names` (optional) | `technical.*` (from `research`) |
| `research` | `providers` | provider bundle, per decision date (slow) |
| `strategy_signal` | `strategy_id` **or** `strategy_key`+`params`, optional `alias` | `signal.<key>` in {-1, 0, 1} |
| `manual_signal` | - | `signal.manual` from `strategies.ManualSignal` |
| `calendar` | `features` (`weekday`, `month`, `day_of_month`, `week_of_year`, `quarter`) | `calendar.<name>` |

The form's structured checkboxes build this list; the raw-JSON textarea
overrides them entirely.

## Target spec

A JSON dict with `type` (`modeling/targets.py`):

| type | params | label |
|---|---|---|
| `horizon_close` | `horizon` (>=1) | close `h` sessions ahead (`h=1` = next-day close) |
| `horizon_return` | `horizon` | pct return over `h` sessions |
| `direction` | `horizon` | 1 if the horizon close is higher, else 0 (classification) |
| `weekday_anchored` | `entry_weekday` (0=Mon), `exit_weekday` (4=Fri) | decision rows are entry-weekday bars; label = same-week exit-weekday close |
| `multistep` | `steps` (>=2) | vector of the next `steps` closes; `ModelPrediction.predicted_json` holds it |

`predict` requires an explicit `target_date` for every type except
`weekday_anchored` (there it is pure calendar arithmetic) - the app does not
invent an exchange holiday calendar, matching `forecasting`.

## Training

`train_model` (`modeling/training.py` / `services.train_model`) never
raises - every outcome is a `ModelTrainingRun` row. It:

1. builds the pooled dataset over `model.instruments` and
   `train_start`/`train_end` (a training row survives only if its label was
   observable by `train_end` - "next local midnight" availability);
2. time-orders the rows and holds out the trailing `holdout_fraction`
   (single split - **not** walk-forward);
3. fits `SimpleImputer -> [StandardScaler] -> estimator`
   (`MultiOutputRegressor`-wrapped for `multistep` when the estimator
   isn't natively multi-output);
4. scores train + holdout (regression: MAE/RMSE/MAPE/R2, directional
   accuracy, skill-vs-naive; classification: accuracy/precision/recall/F1/
   ROC-AUC);
5. `joblib.dump`s the pipeline + feature names to
   `settings.MODEL_ARTIFACT_DIR` (`<repo>/artifacts/models/` by default,
   gitignored; override with `MODEL_ARTIFACT_DIR`).

## Prediction

`predict` (`services.predict`) loads the artifact, builds one point-in-time
feature row, asserts the feature names still match, predicts, and upserts a
`ModelPrediction` (`unique(model, instrument, target_date)`).
`backfill_actuals` fills `actual_value` / `abs_error` once the target
session's bar exists.

## Commands & tasks

```
python manage.py train_model <MODEL_ID> [--start YYYY-MM-DD] [--end YYYY-MM-DD]
python manage.py predict_model <MODEL_ID> <SYMBOL> --as-of YYYY-MM-DD [--target-date YYYY-MM-DD]
python manage.py backfill_actuals [--model <MODEL_ID>]
```

`modeling/tasks.py`: `train_model_task`, `run_model_predictions`,
`backfill_prediction_actuals` - unscheduled, same as the other Phase-7
Celery tasks.

## Limitations

- Single trailing holdout only; no leakage-safe walk-forward yet
  (`forecasting` Phase C).
- Raw prices are not corporate-action adjusted or revision-versioned
  (repo-wide).
- `multistep` stores only the final step's actual in `actual_value`.
- Predictions are not evidence of profitability.
