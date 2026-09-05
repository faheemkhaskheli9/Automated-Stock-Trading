# Forecasting foundation

Phase B tasks B1–B5 are implemented. The Django `forecasting` app registers
`naive` (last observed close) and `drift` (mean training-period one-step
price change). Both return `PricePrediction` objects with a target date,
feature hash and model key. Neither creates orders or writes predictions.

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

Continue B6–B9 with statistical/ML predictors, then B10–B17 with configured
models, forecast persistence, commands and daily tasks. B16 already has
baseline coverage; the remaining predictors still need round-trip tests.
Phase C adds walk-forward validation. See [TASKS.md](TASKS.md).
