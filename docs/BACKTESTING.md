# `backtesting` app - walk-forward backtesting for trading models

Backtests a configured [`modeling.TradingModel`](MODELING.md) in one of two
fit modes:

- **`walk_forward`** (default) - the view the `modeling` app's single trailing
  holdout can't give: retrain the model repeatedly as it marches through
  history, score every out-of-sample fold.
- **`frozen_artifact`** - score the model *as actually trained*: load the
  joblib artifact `modeling.training` already produced (the model's latest, or
  a pinned `training_run`) and run it, unchanged, over every session strictly
  after it was trained. One pseudo-fold; the fold-window fields are ignored.

Either way the pooled out-of-sample forecasts are then turned into positions,
trades and an equity curve by the same code.

Pages (all `login_required`, routed under `/backtests/`):

| URL | Purpose |
|---|---|
| `/backtests/` | List backtests + last-run skill / CAGR headline |
| `/backtests/new/`, `/backtests/<id>/edit/` | Configure a backtest |
| `/backtests/<id>/` | Config, run history, **Run backtest**, aggregate + per-fold metrics, equity curve, predicted-vs-actual chart, predictions CSV |

CLI: `python manage.py backtest_model <backtest_id>
[--fit-mode --training-run --scheme --train-span --test-span --step --gap
--start --end]` (flags override the stored config for that run only;
`--training-run <id>` pins a `ModelTrainingRun` artifact for `frozen_artifact`).
Celery (unscheduled): `backtesting.tasks.run_backtest_task(backtest_id)`,
`run_active_backtests()`.

## Configuration (`Backtest`)

| Field | Meaning |
|---|---|
| `model` | The `TradingModel` to evaluate. Its target must be `horizon_close`, `horizon_return` or `direction` (single scalar per decision). |
| `fit_mode` | `walk_forward` (retrain each fold) or `frozen_artifact` (score the model's already-trained artifact). |
| `training_run` | `frozen_artifact` only: pin which `ModelTrainingRun`'s artifact to score. Blank = the model's latest (`TradingModel.artifact_path`). `clean()` checks it belongs to `model`, succeeded, and has an artifact. |
| `scheme` | `expanding` (train from the first session) or `rolling` (fixed `train_span` window). `frozen_artifact` ignores this and the three span fields. |
| `train_span` / `test_span` / `step` | Sessions of training history / sessions scored per fold / sessions the window advances between folds. Counted in **sessions that have data**, not calendar days. |
| `gap` | Embargo sessions left between a fold's train end and its test start (default 1). |
| `start` / `end` | Optional clamp on the history range fed to `build_dataset`. |
| `long_threshold` | Minimum bullish edge to take a long. `horizon_close`: fractional gap of predicted over the decision close; `horizon_return`: predicted return; `direction`: `P(up) - 0.5`. |
| `allow_short` | Take the symmetric short on a bearish forecast (default off - long/flat only). |
| `initial_cash`, `commission_bps`, `slippage_bps` | Portfolio cash (split equally across instruments) and per-turn trading cost. |

## How a run works (`engine.run_backtest`)

1. `modeling.dataset.build_dataset(model, start, end, for_training=True)` builds
   the full pooled, point-in-time `X / y / anchor / target_dates /
   available_at` (its own trailing holdout split is ignored).
2. `walkforward.generate_folds` cuts the ordered session list into
   `(train, test)` windows. Every fold keeps its whole training block strictly
   before its test block with `gap` sessions of embargo.
3. **`walk_forward`**: per fold, drop any training row whose label was **not**
   observable strictly before the fold's first test decision, fit a **fresh**
   `modeling.training.build_pipeline` on the remaining training rows, predict
   the test rows. Per-fold accuracy comes from `modeling.metrics`.
   **`frozen_artifact`**: skip folds entirely - `joblib.load` the resolved
   artifact (`Backtest.artifact_path`: the pinned `training_run`'s, else the
   model's latest), assert its `feature_names` / `target_spec` still match the
   model, then predict every row whose local decision date is **strictly
   after** the artifact's `trained_at` date. Recorded as a single fold
   (`fold_index=0`, `n_train=0`, `train_end` = the trained-at date).
4. Forecasts -> positions (`metrics.positions_from_forecast`) -> a per-
   instrument all-in/all-out simulation (`metrics.simulate_instrument`,
   costs applied on every position change) -> one pooled portfolio equity
   curve.
5. Trading ratios (total return, CAGR, max drawdown, Sharpe, win rate) are
   read off `strategies.backtesting.engine.BacktestResult` - not re-derived.
6. Everything is persisted: `BacktestRun` (aggregate `metrics` +
   `equity_curve`), `BacktestFold`, `BacktestPrediction`, `BacktestTrade`.
   `run_backtest` never raises - a failure lands on the run as
   `status="failed"` + `error`, exactly like `modeling.training.train_model`.

## Leakage guarantees

- Features are point-in-time (inherited from `modeling.dataset` /
  `modeling.features`).
- A training row is used by a fold only once its label's `available_at`
  (next local midnight after the target session, per the `modeling` /
  `forecasting` convention) is strictly before the fold's first test decision
  timestamp.
- `generate_folds` asserts `train_end < test_start` for every fold and leaves
  `gap` sessions between them.
- `frozen_artifact` scores only sessions strictly after the artifact's
  `trained_at` local date - the artifact never trained on a label observable
  that late, so those rows are genuinely out-of-sample. (In production
  `train_model` runs on near-real-time data, so `trained_at` tracks the last
  available bar. Pin an old `training_run` and this cutoff still uses *that
  run's* `trained_at`.)
- `test_walkforward.py` (randomised fold configs), `test_leakage.py` (per-fold
  availability + disjointness), `test_engine.py` (`naive` skill-vs-naive ~= 0)
  and `test_frozen.py` (one pseudo-fold, cutoff enforced, walk-forward still
  the default) are the canaries.

## v1 limitations

- Single-output targets only - `multistep` and `weekday_anchored` models are
  rejected.
- Position sizing is all-in/all-out per instrument with equal cash allocation;
  no volatility targeting, no `risk` app limits (that app governs *live*
  orders, not this historical replay - same split as
  `strategies/backtesting/engine.py`).
- Folds are chained sequentially; there is no walk-forward hyper-parameter
  search - each fold uses the model's stored `estimator_params`.
- `frozen_artifact` trusts the artifact's `trained_at` as the out-of-sample
  boundary; it does not re-derive the exact last label the pipeline saw. If
  you train a model with an explicit past `train_end` but `trained_at` is
  "now", use `walk_forward` or pin the run whose `trained_at` matches the
  window you mean to evaluate.
- The simulation steps on decision-bar closes; intraday fills, partial fills
  and borrow cost for shorts are out of scope.
