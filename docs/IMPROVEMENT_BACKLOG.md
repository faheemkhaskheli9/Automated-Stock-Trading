# Improvement backlog — models, UI, scalability

Started 2026-09-12 in response to a broad "improve models / UI / make it
scalable" request. Scope was split into: Claude Code **skills** (done, see
`.claude/skills/`), one concrete **model** improvement (done), and this
backlog for the rest — each item is independently shippable and sized so a
session can pick one off without re-deriving context. Track these on
GitHub Projects board #5 alongside Phase 7/8/9 work (per project convention).

## Done this session

- **Claude Code skills** (`.claude/skills/`): `add-modeling-estimator`,
  `add-feature-provider`, `add-forecasting-predictor`,
  `add-operator-ui-page`, `add-scheduled-job` — each encodes this repo's
  registry/point-in-time/design-system conventions so future sessions don't
  re-derive them.
- **`voting_ensemble` estimator** (`modeling/estimators.py`): averages 2+
  already-registered regressors (default `ridge,gradient_boosting,hist_gbr`),
  each with its own scaler where needed, sub-estimators resolved lazily
  from the registry. Cheapest, lowest-risk accuracy lever available today —
  averaging several differently-biased models over any one of them. Tested,
  documented in `docs/MODELING.md`.

## Done 2026-09-12 (session 2)

- **UI: dashboard landing KPI tiles** (`marketdata/views.py::_dashboard_kpis`,
  `marketdata/templates/marketdata/dashboard.html`): a `.stats` row at the
  top of `marketdata:dashboard` showing the top active model's skill score
  (+ next 2 by name), and the signal feed's trailing hit-rate, each linking
  out to its full page. Both sources are read via deferred imports
  (`modeling.leaderboard.build_leaderboard`, a new
  `signalfeed.services.trailing_hit_rate` helper factored out of
  `signalfeed.views.index` so both pages share one query) and degrade
  independently on failure - a KPI must never break the landing page. Fixed
  a pre-existing display bug found along the way: `signalfeed/index.html`
  rendered the fractional `hit_rate` directly with a `%` suffix (e.g. 0.625
  showed as "1%"); now uses `{% widthratio %}` to convert to a percentage,
  same as the new dashboard tile. Tested (`marketdata/tests/test_dashboard.py
  ::DashboardKpiTests`, new `signalfeed/tests/test_services.py` cases for
  `trailing_hit_rate`).

## Done 2026-09-13 (session 3)

- **Wire `voting_ensemble` into `modelsearch`'s default search spaces**
  (`modelsearch/search.py::_auto_ensemble_candidates`): after a sweep
  finishes, `run_search` automatically evaluates one extra
  `voting_ensemble` candidate averaging the top `ModelSearch
  .auto_ensemble_top_k` (new field, default 3, migration `0003`) distinct
  best-scoring base estimators from the run just completed - regression
  tasks only, excludes baseline estimators and a manually-swept
  `voting_ensemble` with the same membership (params-hash dedup). Competes
  for rank/Pareto like any other candidate rather than being bolted on
  separately. Wired through `forms.py`/`views.py::_save`/`admin.py`
  (generic form template needed no template change). Tested
  (`modelsearch/tests/test_search.py`: added, disabled-below-2, skipped for
  classification, dedup-vs-manual cases); documented in
  `docs/MODEL_SEARCH.md` and `CLAUDE.md`. This was Models backlog item #1.
- **`stacking_ensemble` estimator** (`modeling/estimators.py`):
  `sklearn.ensemble.StackingRegressor` over the same registry-lazy
  `estimators` member resolution as `voting_ensemble` (factored into a
  shared `_resolve_ensemble_members` helper), plus a `final_estimator`
  (registry key, default `ridge`) trained on the base models' out-of-fold
  predictions (`cv` folds, default 5). Verified leak-free under
  `backtesting`'s per-fold refit: `StackingRegressor.fit` does its own
  internal CV split on whatever training rows it receives, same as any
  other estimator's `.fit()`. `explain.py` already degrades to `None` for
  it (no special-casing needed - it has neither `coef_` nor
  `feature_importances_`, same path as `voting_ensemble`/`mlp`). Tested
  (`modeling/tests/test_estimators.py`), documented in `docs/MODELING.md`
  and `CLAUDE.md`. This was Models backlog item #2 (stacking ensemble).
- **Async-ify `modelsearch`'s "Run search"** (Scalability item #1, the
  pilot): `services.start_search_run` creates the `ModelSearchRun` row
  (`status="running"`) immediately and enqueues
  `tasks.run_model_search_task.delay(search_id, run_id)` instead of scoring
  inline in the request; `run_search()`/the task now accept an existing
  `run` so the pre-created row is scored into rather than a second one being
  made. Added `CELERY_TASK_ALWAYS_EAGER` (`settings/base.py`, default
  `False`; `settings/dev.py` defaults it `True`) so local dev/tests need no
  worker/broker - `.delay()` just runs inline. `/model-search/<id>/`'s
  detail page shows the `running` row immediately, disables the button, and
  auto-refreshes via a small inline `<script>` (same pattern as the shared
  nav dropdown toggle) until the run finishes. **Deployment caveat
  documented, not yet resolved**: this needs a worker actually consuming
  the broker, which the plan's preferred managed-scheduler shape doesn't
  run persistently (see `docs/DEPLOYMENT.md`) - fine under docker-compose,
  a real gap otherwise. Tested (`modelsearch/tests/test_tasks.py`, existing
  `test_views.py` flow now exercises the async path); documented in
  `docs/MODEL_SEARCH.md`, `docs/DEPLOYMENT.md`, `CLAUDE.md`.

## Models — next candidates (ranked)

1. **Gate `modelsearch`'s ranking on out-of-sample stability, not just the
   single trailing holdout.** Today `modelsearch` scores each candidate on
   one holdout split (documented, intentional v1 limitation — walk-forward
   is `backtesting`'s job). A safe middle ground: after ranking, re-score
   only the top-K candidates through a **short** `backtesting` walk-forward
   run (2-3 folds) before they're eligible for promotion, so a candidate
   that just got lucky on the single split doesn't get promoted blind.
2. **Feature richness**: `research/providers/fundamentals.py` and
   `social.py` are still stubs (CSV/manual load, fixture loader — see
   `gotchas.md`). Real fundamentals ingestion (e.g. a scheduled scrape of
   PSX financial statements, mirroring `psxdata`'s isolation pattern) would
   give every downstream model a genuinely new signal, not just a better
   fit to the same technical features. This is the highest-ceiling, highest
   -effort item on this list.
3. **Regime-awareness**: none of the current estimators condition on
   volatility regime or sector. A `calendar`/`technical` feature already
   exists (`modeling/features.py`); consider a rolling-volatility feature
   and/or a per-sector `ResearchSnapshot` aggregate as new feature-spec
   entries — no new app, just new feature keys.

## UI — next candidates (ranked; no specific complaint was raised, so this
is a proposed punch list, not a confirmed backlog)

1. ~~Dashboard landing KPIs~~ — done 2026-09-12, see above.
2. **Cross-links**: `instrument_detail` already shows a live-forecast panel;
   it does not currently link out to that instrument's `WatchItem` (if any)
   or its `Backtest` history. Adding those links costs a template change,
   not a new view.
3. **Empty/first-run states**: several list pages likely render a bare
   `.empty` message on a fresh install (no instruments synced, no models
   trained yet) — worth a pass to make first-run guidance point at the
   right action (`sync_market_data`, "create your first TradingModel"),
   since this app's onboarding entirely goes through this UI now (Phase 9
   moved everything off admin).
4. **Mobile/responsive pass**: `dashboard.css` is one authored stylesheet
   with token-based light/dark support; audit it at narrow widths (candles
   /SVG charts, `.stat-grid`, wide tables) — `signalfeed` already ships a
   `manifest.webmanifest` for "add to home screen", implying phone use is
   an intended use case worth verifying, not just declaring.
5. **A11y pass**: `_linechart.html` takes an `aria` param already; verify
   every custom SVG chart (candlestick, dashboard close-price) has
   equivalent labeling, and that `.chip`/`.badge` status colors aren't the
   only signal (add text, not just color, for colorblind users).

None of the above should touch `marketdata/tests/test_ui_consistency.py` /
`test_nav.py` / `test_pagination.py`'s enforced structure — see
`.claude/skills/add-operator-ui-page`.

## Scalability — next candidates (ranked)

Audited this session: `marketdata.views.instruments` (a likely N+1 hotspot)
is already correctly batched (`instrument_id__in=ids` + `select_related`,
no per-row query) — commit `347773a` already did a pass here. The real
scalability gaps are architectural, not query-level:

1. ~~**Move `modelsearch`'s Run search off the request thread**~~ — done
   2026-09-13 as the pilot, see above. Several other operator actions are
   still fully synchronous by design (`research:sync`, `execution:run_cycle`,
   `backtesting`'s walk-forward runner, `signalfeed:run`) — fine at today's
   data volume, but a multi-year backtest or a big research sync will
   eventually exceed a request timeout as instrument/history count grows.
   The pattern from `modelsearch` generalizes directly: view calls a new
   `start_*_run`-style service that creates the `*Run` row (`status=running`)
   and `.delay()`s the existing Celery task with that row's id, the task
   accepts an optional pre-created run instead of always making one, and the
   detail template polls the same way (inline `<script>` + disabled button
   while running). The `ModelTrainingRun`/`BacktestRun` models already have
   the pending/running/done/error lifecycle needed — no schema change.
   Remember the deployment caveat that came with the pilot: this needs an
   actually-running worker, which the plan's preferred managed-scheduler
   shape doesn't provide by default (see `docs/DEPLOYMENT.md`).
2. **DB**: dev defaults to sqlite; `docker-compose.yml` provisions Postgres
   but per `gotchas.md` was never actually run. Before relying on
   Postgres-specific behavior (concurrent writes, `JSONField` query
   performance on `feature_spec`/`target_spec`/`params` columns), actually
   bring up `docker-compose up db` once and run the suite against it
   (`DATABASE_URL` env override) to catch sqlite-only assumptions early.
3. **Caching**: `modeling.leaderboard.build_leaderboard` and the dashboard's
   market overview recompute from raw `PriceBar`/`ModelPrediction` rows on
   every request. Neither is provably slow today, but both are natural
   `django.core.cache` candidates (a short TTL, e.g. 5 minutes, invalidated
   naturally by TTL rather than signals — simplest correct option) once
   instrument/prediction counts grow. Don't add caching speculatively
   without a measured slow page first — add a lightweight timing log
   instead, and revisit once real data volume exists.
4. **Horizontal**: `Dockerfile`/`docker-compose.yml` were authored but never
   built (`gotchas.md`). Before any "make it scalable" claim is credible,
   this needs to actually build and run once — that's a prerequisite for
   everything else here (multiple gunicorn workers, a separate Celery
   worker/beat, connection pooling), not an independent task.
5. **Data growth**: `PriceBar` is unique per
   `instrument+timeframe+timestamp` (already indexed, `marketdata/models.py`)
   and `bulk_create(update_conflicts=True)` is already used for sync — this
   part scales fine. The one true gap: no data retention/partitioning
   policy for `NewsItem`/`ModelPrediction`/`BacktestPrediction` — these grow
   unboundedly with no archival job. Not urgent at current scale; revisit
   once there's real multi-year, multi-instrument history.

## Suggested order for future sessions

Highest ratio of value to risk, in order: (1) ~~UI KPI tiles~~ done
2026-09-12, (2) ~~wire `voting_ensemble` into `modelsearch`~~ / ~~stacking
ensemble~~ / ~~async-ify `modelsearch`'s Run search~~ done 2026-09-13, (3)
generalize the async pattern to the next heavy action (`backtesting`'s
walk-forward runner is the next-best candidate — same `*Run` lifecycle
shape already exists), (4) actually build/run Docker once (also resolves
the async-worker deployment caveat above), (5) everything else, gated on
real usage data rather than speculation.
