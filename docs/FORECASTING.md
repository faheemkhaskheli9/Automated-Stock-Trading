# Forecasting foundation

Phase B tasks B1–B7 are implemented. The Django `forecasting` app registers
`naive` (last observed close), `drift` (mean training-period one-step price
change), `sarima`/`ets` (univariate statistical), and `ridge`/`elasticnet`
(regularised linear over the full feature frame). Every predictor returns
`PricePrediction` objects with a target date, feature hash and model key.
None create orders or write predictions.

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
and there is no walk-forward evaluation or persistent forecast audit yet.
The hashes identify assembled feature values, not full dataset versions.

## Next tasks

Continue B8–B9 with the tree / optional-LSTM predictors, then B10–B17 with
configured models, forecast persistence, commands and daily tasks. B16 has
baseline, statistical and linear coverage; the tree/LSTM predictors still
need round-trip tests. Phase C adds walk-forward validation. See
[TASKS.md](TASKS.md).

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
and confidence remain unset. Walk-forward fold creation remains Phase C.

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
