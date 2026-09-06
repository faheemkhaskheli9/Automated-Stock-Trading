# Forecasting foundation

Phase B tasks B1–B9 are implemented. The Django `forecasting` app registers
`naive` (last observed close), `drift` (mean training-period one-step price
change), `sarima`/`ets` (univariate statistical), `ridge`/`elasticnet`
(regularised linear over the full feature frame), `gradient_boosting`
(histogram gradient-boosted trees over the same feature frame), and -- only
when the optional `torch` extra is installed -- `lstm` (a PyTorch sequence
model over the same frame). Every predictor returns `PricePrediction` objects
with a target date, feature hash and model key. None create orders or write
predictions.

## Try the baselines

With historical daily bars already stored, run
`.venv/Scripts/python.exe manage.py shell` and enter the following. Replace
the symbol, dates and explicit target date with ones appropriate to your
stored data and verified exchange calendar:

```python
from datetime import datetime, date
from zoneinfo import ZoneInfo
from forecasting.features import assemble_training_frame
from forecasting.registry import get_predictor_class

zone = ZoneInfo("Asia/Karachi")
cutoff = datetime(2026, 9, 4, tzinfo=zone)
train = assemble_training_frame(
    "ENGRO", datetime(2026, 1, 1, tzinfo=zone), cutoff
)
predictor = get_predictor_class("drift")()
predictor.fit(train)
forecast = predictor.predict_next(
    "ENGRO", cutoff, target_date=date(2026, 9, 4)
)
print(forecast)
```

No completed history is an explicit error. Missing indicator warmups remain
NaN; later trainable models must fit their imputers/scalers only on training
data. Intervals and confidence remain `None` because these baselines do not
estimate calibrated uncertainty. Predictions are not evidence of profitability.

## Time and label contract

- Daily bars are treated as available at the **following local midnight**,
  irrespective of their stored timestamp. This avoids using an EOD close
  before the session finishes. Same-evening forecasting requires a later
  change to store reliable session-close/publication timestamps.
- `start` and `end` are aware decision timestamps. Training uses features
  at or after `start`, and only labels available at or before `end`.
  Earlier bars remain available for indicator warmup.
- `TrainingFrame.inputs` is a `PredictionFrame` containing numeric `X`,
  target-date metadata and per-row hashes. Actual future closes (`y`) and
  their availability timestamps are separate. Pass only `.inputs` to
  `predict_series`; passing a `TrainingFrame` is rejected by the baselines.
- Targets are the **next observed daily bar**. A missing bar or suspension
  can lengthen the horizon. A verified session calendar is still needed to
  distinguish missing observations from holidays. `predict_next` requires
  an explicit target date and does not inspect future bars to guess it.
- Drift fits the average of `y - price.close` on its training slice. It
  rejects inference before the latest training label was available and
  rejects inference for a different symbol/exchange.
- Research features are rebuilt at each cutoff. Technical indicators use
  only the eligible price prefix; external providers must return matching
  symbol, exchange and cutoff metadata. Provider errors, collisions,
  non-finite features, anomalous bars and inconsistent OHLC values fail
  explicitly. Date-only fundamental releases become usable the next day.
- `exchange_timezone` is configurable; it defaults to `Asia/Karachi`.
  `provider_keys` can select an explicit feature set during assembly.

These guards enforce timestamp boundaries, not the truth of source metadata.
Raw prices are not corporate-action adjusted, historical revisions are not
versioned, provider internals cannot be universally checked for future reads,
and there is no persistent forecast audit yet. The hashes identify assembled
feature values, not full dataset versions.

## Next tasks

Phase B predictors are complete (B9's optional LSTM below). B10–B17
(configured models, forecast persistence, commands, daily tasks) are
delivered in the parallel `modeling` app; B16's LSTM round-trip tests run
only where the `torch` extra is installed. Phase C walk-forward validation
for these strict predictors now exists (`forecasting/backtesting/`, below),
and a run can be persisted as a `ForecastBacktestRun` row
(`run_forecast_backtest` / `backtest_predictor --save`). The symbol-detail
"next-session forecast" panel (D4) is live: `forecasting.services.latest_forecast(
symbol, predictor_key)` returns a never-raises `LiveForecast` (predicted
close, optional interval/confidence, model, target date) that the
`marketdata` symbol-detail page renders with a `?predictor=` picker. It
fits the chosen predictor on all history before the day after the last
stored bar, uses price + `technical` features only, and targets the next
weekday — a convenience estimate, not the leakage-strict operational path.
The accuracy leaderboard (D8) is live in the `modeling` app. The strict-path
backtest runner (D7) is live at `/forecast-backtests/` — see below. See
[TASKS.md](TASKS.md).

## Dashboard backtest runner (D7)

`/forecast-backtests/` is a thin UI over
`forecasting.services.run_forecast_backtest`. The **New backtest** form
(`forecasting.forms.ForecastBacktestForm`) collects a registered predictor
key, one PSX symbol, JSON predictor params, the research providers (`none`
for price-only), the fold windows (`scheme` / `train_span` / `test_span` /
`step` / `gap`), the `start`/`end` dates and the long-if-up trading rule
(`long_threshold` / `allow_short` / `cost_bps` / `initial_cash`). Submitting
runs one walk-forward **synchronously** and always persists a
`ForecastBacktestRun` — a failure lands on the row and is shown as a message,
never a 500. The detail page renders the aggregate metric cards (MAE / RMSE /
directional accuracy / **skill vs. naive** / R² and the trading translation),
an equity-curve SVG, a predicted-vs-actual SVG, the per-fold table and any
skipped folds, plus a `?export=csv` of the pooled OOS predictions. It trips
the same `looks_leaky` canary banner as the CLI. Server-rendered, no
htmx/Plotly — the same Phase D style as the rest of the dashboard;
`backtesting/` (`/backtests/`) is the counterpart for `modeling.TradingModel`
artifacts.

## Walk-forward backtesting (Phase C)

`forecasting/backtesting/` evaluates a single registered predictor over
rolling / expanding folds with a hard train/test boundary. It is the
`forecasting.BasePredictor` counterpart to the standalone `backtesting`
app (which scores `modeling.TradingModel` artifacts).

```
python manage.py backtest_predictor OGDC ridge \
    --start 2023-01-01 --end 2025-06-01 \
    --scheme expanding --train-span 250 --test-span 21 --step 21 --gap 1 \
    --providers none --cost-bps 15
```

Prints a per-fold table, pooled MAE / RMSE / MAPE / R², directional
accuracy, **skill vs. naive** (`1 - mae / naive_mae`; positive beats a
random walk), and a "long if the forecast is up" trading translation
(total / annualised return, max drawdown, Sharpe, hit rate). It warns when
the out-of-sample skill is implausibly high — the built-in leak canary.

Leakage guarantees, enforced by tests (`forecasting/tests/test_walk_forward.py`):

- **Fold disjointness.** `walkforward.generate_folds` returns contiguous
  row-position windows with `max(train) < min(test)` and a `gap`-session
  embargo, asserted on every fold and fuzzed over 40 random configs.
- **Fresh predictor per fold.** `engine.walk_forward` instantiates the
  predictor class anew for each fold and calls `fit` on that fold's training
  slice only — no scaler, imputer or fitted object crosses the boundary.
- **Point-in-time features.** The training frame is assembled once by
  `assemble_training_frame`; features for row *t* only ever see history
  `<= t`, so slicing folds out of it afterwards cannot leak.
- **Label availability.** A training row is dropped from a fold if its label
  was not observable strictly before that fold's first test decision.
- **Leak canary.** A deliberately future-peeking predictor (reads the target
  close from the DB) is flagged by `engine.looks_leaky`; `naive` is not.

`walk_forward` returns a `WalkForwardResult` (per-fold `FoldReport`s, pooled
`predictions`, `metrics`, `naive_metrics`, `trading`, `skipped_folds`).

### Persisting a run

`forecasting.services.run_forecast_backtest(...)` runs the walk-forward and
freezes it as a `forecasting.ForecastBacktestRun` row — one flat record
holding both the config (predictor key + params + symbol + fold scheme +
trading rule) and the results (`folds`, `predictions`, `metrics`,
`naive_metrics`, `trading`, `equity_curve`, `looks_leaky`). Dates are
serialised to ISO strings so every field is JSON-safe for the API / a future
dashboard. Like `backtesting.engine.run_backtest`, it **never raises**: a
failure lands on the row as `status="failed"` + `error`. There is no
admin-configured "predictor model" on this path (that intent lives in
`modeling.TradingModel`), so each run carries its own config.

Add `--save` (optionally `--name`) to the command to persist instead of
print:

```
python manage.py backtest_predictor OGDC ridge --start 2023-01-01 \
    --end 2025-06-01 --providers none --save --name "ridge OGDC 23-25"
```

One predictor, one symbol per run; multi-instrument pooling and prediction
intervals are out of scope for this pass. No dashboard runner yet.

## Statistical predictors (B6)

Use `get_predictor_class("sarima")()` or `get_predictor_class("ets")()` with
`fit(train)` and `predict_series(frame)` / `predict_next(...)`. Install the
updated requirements first. SARIMA defaults to order `(1, 1, 0)` with no
seasonality; configure `order`, `seasonal_order`, and `trend`. ETS defaults
to additive error with no trend or seasonality; configure `error`, `trend`,
`damped_trend`, `seasonal`, and `seasonal_periods`. Seasonal periods count
observed sessions, not calendar days. Insufficient data, invalid model
specifications, and failed convergence raise errors without a fallback.

Training requires at least three contiguous labelled rows and includes the
final known target close once. Each fit creates a new statsmodels model.
Replay must start exactly at `predictor.fitted_through` (the final training
label availability timestamp), with that same observed close, and supply
every subsequent observed session in order. For a standalone forecast,
fit through its decision timestamp first. This strict boundary avoids
silently skipping observations or counting the final training close twice.
Intraday timestamps beyond the final label boundary are currently rejected.
A verified calendar is still needed to detect gaps in caller-supplied replay.

Each prediction smooths only the available prefix using fixed fitted
parameters; inference never refits or preserves test state between calls.
Only closing prices are used; other research features are ignored. Intervals
and confidence remain unset. Because `predict_series` demands a contiguous
replay starting exactly at `fitted_through`, the walk-forward harness (below)
cannot score `sarima`/`ets` across its `gap` embargo — those folds are
skipped rather than silently misaligned. Run them with `--gap 0` or drive
replay manually.

Implementation references: [SARIMAX](https://www.statsmodels.org/stable/generated/statsmodels.tsa.statespace.sarimax.SARIMAX.html)
and [ETS smoothing with fixed parameters](https://www.statsmodels.org/stable/generated/statsmodels.tsa.exponential_smoothing.ets.ETSModel.smooth.html).

## Linear predictors (B7)

`get_predictor_class("ridge")()` / `get_predictor_class("elasticnet")()` are
`BasePredictor` subclasses that use the **whole** assembled feature frame —
price lags/returns plus any `research` bundles selected by `provider_keys` —
not just the close. `RidgePredictor(alpha=1.0)` and
`ElasticNetPredictor(alpha=0.1, l1_ratio=0.5)` are configurable.

- The learning target is the next-session **simple return**
  `y / price.close - 1`. Each forecast is rebuilt as
  `price.close * (1 + predicted_return)`, so a near-zero prediction
  reproduces the naive last-close baseline and predictions stay on a price
  scale.
- `fit()` builds an sklearn `Pipeline`: median `SimpleImputer`
  (`keep_empty_features=True`, so an all-NaN indicator warmup column keeps
  its slot) → `StandardScaler` → `Ridge` / `ElasticNet`. The imputer and
  scaler are fit **only** on the supplied `TrainingFrame` — never across a
  fold boundary, never on the full series. At least five training rows are
  required.
- The training feature-column list is pinned at `fit()`. `predict_series`
  rejects a frame whose columns differ (assemble both frames with the same
  `provider_keys`). It also rejects a `TrainingFrame`, a different
  symbol/exchange, and any row whose decision timestamp precedes the last
  training label's availability (`fitted_through`). A failed refit clears the
  fitted pipeline.
- Prediction is per-row and independent: unlike `sarima`/`ets` there is no
  prefix replay, so `predict_series` accepts any batch of eligible rows in
  order. Intervals and confidence stay `None` — these models do not estimate
  calibrated uncertainty. A pathological predicted return below `-100%` makes
  the reconstructed close non-positive and raises rather than being clipped.

## Gradient-boosted trees (B8)

`get_predictor_class("gradient_boosting")()` is a `GradientBoostingPredictor`
wrapping sklearn's `HistGradientBoostingRegressor`. It shares every part of
the linear (B7) contract — same next-session simple-return target, same
`price.close * (1 + predicted_return)` reconstruction, same pinned
feature-schema / instrument / `fitted_through` guards, same failed-refit
state clearing, same per-row independence and unset intervals — through the
common `forecasting._frame_model.FrameModelPredictor` base.

The one difference is the pipeline: `HistGradientBoostingRegressor` handles
NaNs natively and needs no feature scaling, so the pipeline is just the
estimator (no `SimpleImputer`, no `StandardScaler`). Configurable via
`GradientBoostingPredictor(learning_rate=0.1, max_iter=200, max_depth=None,
min_samples_leaf=20, l2_regularization=0.0, random_state=0)`; `random_state`
is pinned by default for reproducible fits. At least five training rows are
required.

## Optional LSTM predictor (B9)

`lstm` is registered **only** when the optional `torch` extra is installed
(`pip install -r requirements-ml.txt`). Without it `forecasting.deep` still
imports cleanly, `forecasting.deep.LSTM_AVAILABLE` is `False`, and
`get_predictor_class("lstm")` raises — nothing else in the app or test suite
depends on torch.

`LstmPredictor(lookback=20, hidden_size=32, layers=1, epochs=60, lr=1e-3,
random_state=0)` shares the same `FrameModelPredictor` contract as B7/B8:
next-session simple-return target, `price.close * (1 + predicted_return)`
reconstruction, pinned feature schema, instrument / `fitted_through` guards,
failed-refit state clearing, unset intervals. The pipeline is a median
`SimpleImputer` (`keep_empty_features=True`) → a small sklearn-wrapped
`nn.LSTM` that standardises its inputs internally and predicts from the last
`lookback` feature rows.

Sequence caveat: the predictor keeps no training tail, so at inference the
first `lookback - 1` rows of a frame are left-padded with a copy of that
frame's first row rather than real prior history — a single-row `predict_next`
call degenerates to a window of copies. Forecasts stay causal (row `i` uses
only rows `≤ i` in the frame). This mirrors `modeling.deep` and is adequate
for a v1; walk-forward evaluation is Phase C.
