# `modelsearch` app - parameter / model search

Finds an **efficient, accurate** predictor by sweeping several estimators and
hyper-parameter grids at once, instead of hand-editing one `modeling.TradingModel`
and retraining it over and over.

A search is seeded from an existing `TradingModel`: it copies that model's
feature spec, target spec, instruments and train window, then evaluates every
candidate `(estimator, params)` combination on the **same single trailing
holdout** the `modeling` studio uses (`scoring_mode = "holdout"`, the
default), or by refitting each candidate on every `backtesting.walkforward`
fold and pooling the out-of-sample predictions (`scoring_mode =
"walk_forward"`) - see "Scoring mode" below. The dataset is built once and
reused across all candidates. Results are ranked by a chosen accuracy metric,
and fit time / per-row predict latency / serialized model size are recorded
so the speed-vs-accuracy trade-off is visible. The winner is one click from
being **promoted** into a new `TradingModel` for the normal `/modeling/`
train -> predict flow.

No per-candidate artifacts are written - only the promoted winner is trained
and dumped, by `modeling`.

Pages (all `login_required`, routed under `/model-search/`):

| URL | Purpose |
|---|---|
| `/model-search/` | List searches + last run status + best candidate |
| `/model-search/new/` (`?from=<TradingModel id>`), `/model-search/<id>/edit/` | Configure a search |
| `/model-search/<id>/` | Config, **Run search** (async - see below), ranked candidate table, accuracy-vs-fit-time scatter, **Promote**, run history |

## Running a search (async)

"Run search" no longer blocks the request: it creates the `ModelSearchRun`
row (`status="running"`) immediately and hands the actual sweep to
`modelsearch.tasks.run_model_search_task` via Celery
(`services.start_search_run`). The detail page shows that row right away and
auto-refreshes (a small inline `<script>`, same pattern as the shared nav's
dropdown toggle - no HTMX/build step) every few seconds while it's
`"running"`; the **Run search** button is disabled meanwhile so a second
click can't start a duplicate run.

Locally, `CELERY_TASK_ALWAYS_EAGER=True` (the `dev.py` default - no worker or
broker needed) makes `.delay()` run the task inline, so in practice a local
"Run search" click still finishes before the redirect - the async path is
exercised the same way it will be in production, just without an actual
queueing delay. Set `CELERY_TASK_ALWAYS_EAGER=False` (`.env`) to test the
polling path against a real Celery worker + broker.

The CLI (`run_model_search` management command) and
`modelsearch.services.run_search()` still run fully synchronously in the
calling process - unchanged, since a one-off script/cron invocation has no
request thread to free up.

**Deployment caveat**: `.delay()` needs a worker actually consuming the
broker. The Docker Compose deployment shape runs one (`docker-compose.yml`'s
`worker` service) so this just works; the managed-scheduler shape
(`docs/DEPLOYMENT.md`'s preferred shape, one-off container tasks with no
persistent Celery process) does **not** run one by default - deploying that
shape without also running a small always-on worker leaves a search stuck
`"running"` forever.

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

Every candidate also stores the full `modeling.metrics` blob it was ranked on.

## Scoring mode

`ModelSearch.scoring_mode`:

- `"holdout"` (default) - each candidate is fit once on the trailing-holdout
  train slice and scored on the held-out slice, same as before. Fast, but a
  single split can disagree with how a model actually holds up over time.
- `"walk_forward"` - each candidate is refit on every
  `backtesting.walkforward.generate_folds` fold (`wf_scheme`/`wf_train_span`/
  `wf_test_span`/`wf_step`/`wf_gap`, same fields and defaults as
  `backtesting.Backtest`) and the out-of-sample predictions are pooled across
  folds into one metrics blob - that pooled score is what ranks candidates.
  The single-holdout score/metrics for the same candidate are also computed
  and kept under `metrics["holdout"]` / `metrics["holdout_score"]`, and
  `ModelSearchResult.wf_folds` records how many folds were pooled - this is
  exactly the holdout-vs-walk-forward divergence check this mode exists for,
  shown side by side on `/model-search/<id>/`.
  This is `candidates x folds` model fits, so it costs proportionally more
  wall-clock than `"holdout"` - shrink `max_candidates` or widen
  `wf_test_span`/`wf_step` if a run gets too slow. A dataset too short for one
  fold fails the whole run (same as `backtesting`) rather than silently
  falling back to holdout.

## Auto-ensemble

After the sweep finishes, `run_search` also tries one extra
`voting_ensemble` candidate (see `modeling`'s estimator of the same name)
averaging the `ModelSearch.auto_ensemble_top_k` best-scoring **distinct**
base estimators from the run just completed (default `3`; `0` or `1`
disables it). This is regression-only (`voting_ensemble` doesn't support
classification) and skips:

- baseline estimators (`naive_last` / `drift` / `seasonal_naive`) as
  members - same rule `modeling.estimators._build_voting_ensemble` enforces,
- adding a duplicate when the operator already swept a `voting_ensemble`
  candidate with the exact same membership (matched by params hash).

The auto candidate competes for rank / Pareto status exactly like any
manually-swept one - it isn't bolted on separately - so a search over
several single models gets a free "does averaging the winners help"
comparison point without hand-adding it to `search_space`.

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

- Default `"holdout"` mode is a single trailing split - a fast comparative
  read, not a robust out-of-sample estimate. `"walk_forward"` mode narrows
  that gap for the search itself, but still runs on the search's own dataset
  window; confirm a promoted model's live behavior with the `backtesting` app.
- Timing numbers are wall-clock on the machine running the search; treat them as
  relative, not absolute SLAs.
- Baseline estimators (`naive_last` / `drift` / `seasonal_naive`) need the
  matching `ohlc` close lag in the feature spec or their candidate is recorded
  as `failed` (same rule as `modeling`).
