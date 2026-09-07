# `modelsearch` app - parameter / model search

Finds an **efficient, accurate** predictor by sweeping several estimators and
hyper-parameter grids at once, instead of hand-editing one `modeling.TradingModel`
and retraining it over and over.

A search is seeded from an existing `TradingModel`: it copies that model's
feature spec, target spec, instruments and train window, then evaluates every
candidate `(estimator, params)` combination on the **same single trailing
holdout** the `modeling` studio uses. The dataset is built once and reused
across all candidates. Results are ranked by a chosen accuracy metric, and fit
time / per-row predict latency / serialized model size are recorded so the
speed-vs-accuracy trade-off is visible. The winner is one click from being
**promoted** into a new `TradingModel` for the normal `/modeling/` train ->
predict flow.

**Not** walk-forward (that is the `backtesting` app) and **no** per-candidate
artifacts are written - only the promoted winner is trained and dumped, by
`modeling`.

Pages (all `login_required`, routed under `/model-search/`):

| URL | Purpose |
|---|---|
| `/model-search/` | List searches + last run status + best candidate |
| `/model-search/new/` (`?from=<TradingModel id>`), `/model-search/<id>/edit/` | Configure a search |
| `/model-search/<id>/` | Config, **Run search** (synchronous), ranked candidate table, accuracy-vs-fit-time scatter, **Promote**, run history |

## Search space

`ModelSearch.search_space` is a JSON object:

```json
{
  "estimators": ["ridge", "gradient_boosting", "random_forest"],
  "param_grids": {
    "ridge": {"alpha": [0.1, 1.0, 10.0]},
    "gradient_boosting": {"n_estimators": [100, 300], "learning_rate": [0.03, 0.1]}
  }
}
```

- Every estimator key must be in `modeling`'s registry (`/modeling/estimators/`),
  be available in this environment, and match the target's task
  (regression / classification).
- An estimator listed with no `param_grids` entry contributes exactly one
  candidate at its registry defaults.
- Param names / types are validated against each estimator's `param_schema`
  (`BaseEstimatorSpec.coerce_params`), so a bad name or an uncoercible value is
  rejected at save time.
- `mode = "grid"` evaluates every combination (capped at `max_candidates` in
  expansion order); `mode = "random"` samples `max_candidates` with
  `random_seed` (reproducible).

Expansion / validation lives in `modelsearch/spaces.py` (no Django imports, like
`modeling.features` / `modeling.targets`).

## Scoring

`ModelSearch.scoring` picks the ranking scalar (blank = the task default):

- regression: `directional_accuracy` (default), `skill_vs_naive`, `r2`,
  `neg_mae`, `neg_rmse` (errors are negated so "higher is better" always holds).
- classification: `accuracy` (default), `roc_auc`, `f1`, `precision`, `recall`.

Every candidate also stores the full `modeling.metrics` holdout blob.

## Pareto front

`ModelSearchResult.is_pareto` marks candidates **not dominated** on all four of
`(score up, fit_seconds down, predict_latency_ms down, model_size_bytes down)`.
These are the efficient frontier - the fastest / smallest model at each accuracy
level. The scatter on the detail page rings them.

## Promote

"Promote" on a result row creates a new `modeling.TradingModel`:

- `estimator_key` / `estimator_params` from the result,
- `feature_spec` / `target_spec` / instruments / train window / holdout fraction
  from the search.

It is **not** trained automatically - land on `/modeling/<new id>/` and press
**Train now**.

## CLI / task

- `python manage.py run_model_search <search_id> [--seed N] [--max N]` - runs a
  search and prints the top 5. Shares `modelsearch.services.run_search` with the
  UI button and the Celery task.
- `modelsearch.tasks.run_model_search_task(search_id)` - unscheduled, same as
  `modeling.tasks`.

## Limitations

- Single trailing holdout, not walk-forward - a fast comparative read, not a
  robust out-of-sample estimate. Confirm a promoted model with the `backtesting`
  app.
- Timing numbers are wall-clock on the machine running the search; treat them as
  relative, not absolute SLAs.
- Baseline estimators (`naive_last` / `drift` / `seasonal_naive`) need the
  matching `ohlc` close lag in the feature spec or their candidate is recorded
  as `failed` (same rule as `modeling`).
