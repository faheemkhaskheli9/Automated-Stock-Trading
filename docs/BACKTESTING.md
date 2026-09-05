# `backtesting` app - walk-forward backtesting for trading models

Backtests a configured [`modeling.TradingModel`](MODELING.md) the way the
`modeling` app's single trailing holdout can't: retrain the model repeatedly
as it marches through history, score every out-of-sample fold, then turn the
pooled forecasts into positions, trades and an equity curve.

Pages (all `login_required`, routed under `/backtests/`):

| URL | Purpose |
|---|---|
| `/backtests/` | List backtests + last-run skill / CAGR headline |
| `/backtests/new/`, `/backtests/<id>/edit/` | Configure a backtest |
| `/backtests/<id>/` | Config, run history, **Run backtest**, aggregate + per-fold metrics, equity curve, predicted-vs-actual chart, predictions CSV |

CLI: `python manage.py backtest_model <backtest_id>
[--scheme --train-span --test-span --step --gap --start --end]` (flags
override the stored config for that run only).
Celery (unscheduled): `backtesting.tasks.run_backtest_task(backtest_id)`,
`run_active_backtests()`.

## Configuration (`Backtest`)

| Field | Meaning |
|---|---|
| `model` | The `TradingModel` to evaluate. Its target must be `horizon_close`, `horizon_return` or `direction` (single scalar per decision). |
| `scheme` | `expanding` (train from the first session) or `rolling` (fixed `train_span` window). |
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
3. Per fold: drop any training row whose label was **not** observable strictly
   before the fold's first test decision, fit a **fresh**
   `modeling.training.build_pipeline` on the remaining training rows, predict
   the test rows. Per-fold accuracy comes from `modeling.metrics`.
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
- `test_walkforward.py` (randomised fold configs), `test_leakage.py` (per-fold
  availability + disjointness) and `test_engine.py` (`naive` skill-vs-naive
  ~= 0) are the canaries.

## v1 limitations

- Single-output targets only - `multistep` and `weekday_anchored` models are
  rejected.
- Position sizing is all-in/all-out per instrument with equal cash allocation;
  no volatility targeting, no `risk` app limits (that app governs *live*
  orders, not this historical replay - same split as
  `strategies/backtesting/engine.py`).
- Folds are chained sequentially; there is no walk-forward hyper-parameter
  search - each fold uses the model's stored `estimator_params`.
- The simulation steps on decision-bar closes; intraday fills, partial fills
  and borrow cost for shorts are out of scope.
