# Task List — Phase 7: Next-Day Close Forecasting

Living checklist for `docs/FORECASTING_PLAN.md`. **Keep this updated as work
lands** — flip status, add notes, check boxes in the same commit as the
change.

Status legend: ⬜ Not started · 🟡 In progress · ✅ Done · ⛔ Blocked · ⏭️ Deferred

## Current status (2026-09-06)

- Phase A is complete. Phase B foundation (B1–B5) is committed as `40b4265`.
- Latest validation: **`forecasting` suite 54 passed, 6 skipped** (the skips
  are B9's `test_deep.py::TestWithTorch`, which needs the optional `torch`
  extra); Django check and Black/isort/Ruff clean for `forecasting`. Full
  suite **283 passed, 6 skipped** after B9. Remote CI has not been verified.
- Phase C (walk-forward backtesting) is complete as the standalone
  `backtesting` app over `modeling.TradingModel` — see the Phase C table and
  `docs/BACKTESTING.md`. `Backtest.fit_mode` now also offers
  `frozen_artifact`: score a `modeling`-trained joblib artifact (latest or a
  pinned `training_run`) over every session after it was trained, instead of
  retraining per fold (migration `0002`, `test_frozen.py`).
- The `modeling` app (commit `11a4bf0`, branch `phase7-modeling-app`)
  delivers the configurable-model + persistence intent as a **parallel app**
  to `forecasting`: covers B10–B15, B17 and D6, and partially B7–B9 / B16 /
  E2 / E3 (see the tables below). It uses sklearn `Pipeline` estimators + a
  single trailing holdout, **not** `forecasting.BasePredictor` prefix-replay
  or walk-forward.
- **Next task for the strict `forecasting` path: C-phase walk-forward for the
  `forecasting` predictors** (the current `backtesting` app is over
  `modeling.TradingModel`, not `forecasting.BasePredictor`).
- B6, B7, B8 and B9 are complete. B9 (`forecasting/deep.py`) adds the optional
  `lstm` predictor: a `FrameModelPredictor` subclass (median imputer →
  sklearn-wrapped `nn.LSTM`) that soft-imports `torch` and registers nothing
  when the extra is absent. B7 (`forecasting/linear.py`) and B8
  (`forecasting/trees.py`) share one fit/predict/leakage-guard base
  (`forecasting/_frame_model.py::FrameModelPredictor`): full point-in-time
  feature frame, next-return target, pinned feature schema. Linear adds an
  imputer+scaler pipeline stage; `gradient_boosting`
  (`HistGradientBoostingRegressor`) takes the raw matrix. Walk-forward
  evaluation (Phase C) and the forecasting dashboard's forecast panels (D4,
  D7, D8) remain pending.
- The PSX data viewer is complete: authenticated browsing, fetch-and-save, date
  filters, closing-price chart and CSV export in `marketdata`. Its 25 market-data
  tests pass; live PSX connectivity and remote CI have not been verified.
- Web UI shell: a shared authenticated menubar in `marketdata/base.html`
  (Market Data / Backtesting / Modeling / Admin / API) and a `strategies`
  backtesting page at `/backtesting/` (rule or saved strategy vs stored
  daily bars → equity curve + stats + trade ledger + CSV, with next-open
  fills and commission/slippage costs). Both are separate from the pending
  forecasting dashboard (D1–D10).
- Usage and timing limitations: [FORECASTING.md](FORECASTING.md).

---

## Phase A — `research` app (feature / signal library) — ✅ complete (2026-09-05)

12 new tests, full suite 112 green, `black`/`isort`/`ruff` clean, `manage.py check` clean.

| # | Task | Status | Notes |
|---|------|--------|-------|
| A1 | Create `research` app; register in `INSTALLED_APPS`; `apps.ready()` imports concrete providers | ✅ | `research/apps.py` |
| A2 | `providers/base.py`: `FeatureProvider` ABC + `FeatureBundle` dataclass + point-in-time contract docstring | ✅ | `+ register_feature_provider` registry, `FeatureBundle.merge` guards key collisions |
| A3 | `providers/technical.py`: indicator library (SMA/EMA/RSI/MACD/Bollinger/ATR/stochastic/OBV/ROC/vol/volume-z/gap), pure-pandas with optional `pandas-ta` soft import | ✅ | `technical_features(df)` pure fn + `load_ohlcv` DB loader + `TechnicalProvider` |
| A4 | Technical-indicator tests against hand-computed fixtures | ✅ | `tests/test_technical.py` (6 tests) |
| A5 | `providers/news.py` + `NewsItem` model: `feedparser` RSS ingest, per-exchange feed config, idempotent on URL hash | ✅ | `feedparser` soft-imported; `ingest_feeds()`; feeds via `settings.RESEARCH_NEWS_FEEDS` |
| A6 | VADER sentiment on headlines; news-derived features (count/mean/last/trend, windowed `< as_of`) | ✅ | `vaderSentiment` soft-imported; `news_features()` |
| A7 | `providers/fundamentals.py` + `CompanyFundamental` model: interface + CSV/manual loader; live scrape = TODO | ✅ | interface + `load_fundamentals_csv` done; live scrape still ⏭️ deferred |
| A8 | `providers/social.py` + `SocialMention` model: interface + fixture loader; live X/Reddit/StockTwits = TODO | ✅ | interface + `load_mentions` done; live ingestion still ⏭️ deferred |
| A9 | `services.build_feature_bundle()` merges provider outputs | ✅ | per-provider failure logged + skipped, never aborts |
| A10 | `ResearchSnapshot` model + `get_or_build` upsert; migration | ✅ | `services.get_or_build_snapshot`; `migrations/0001_initial.py` |
| A11 | `management/commands/sync_research.py` (`--symbol`, `--as-of`) | ✅ | also `--exchange`, `--no-news`, `--rebuild` |
| A12 | `research.tasks.sync_all_research` Celery task (unscheduled) | ✅ | `+ ingest_news` task; per-symbol failure isolation |
| A13 | Leak test: post-`as_of` headline is excluded from the bundle | ✅ | `tests/test_point_in_time.py` (5 tests: technical + news + bundle) |
| A14 | `research` admin registrations | ✅ | `research/admin.py` — all 4 models |
| A15 | `requirements.txt`: add `feedparser`, `vaderSentiment` | ✅ | soft-imported; suite runs without them |

## Phase B — `forecasting` app (predictor framework) — 🟡 in progress

| # | Task | Status | Notes |
|---|------|--------|-------|
| B1 | Create `forecasting` app; register; `apps.ready()` imports predictor modules | ✅ | `forecasting/apps.py`; registers baseline predictors at startup |
| B2 | `base.py`: `BasePredictor` ABC (`fit`/`predict_next`/`predict_series`) + `PricePrediction` dataclass | ✅ | `BasePredictor`, `PricePrediction`, separate label-free `PredictionFrame` and `TrainingFrame` |
| B3 | `registry.py`: `@register_predictor` / `get_predictor_class` / `registered_keys` | ✅ | Explicit registry with duplicate-key validation and informative lookup errors |
| B4 | `features.py`: `assemble_training_frame()` — lag/return features + `research` bundle as-of each bar; target = next close | ✅ | Completed-day availability; aligned next-observed labels; cutoff feature hashes; no future labels in inputs |
| B5 | `naive.py`: `NaiveClosePredictor`, `DriftPredictor` (baselines) | ✅ | `naive` / `drift`; drift rejects inference before fitted labels are available |
| B6 | `stats.py`: `SarimaPredictor`, `EtsPredictor` (`statsmodels`), refit per fold | ✅ | Training-only fits, prefix replay and cutoff guards; 11 new tests; fold orchestration remains C1 |
| B7 | `linear.py`: `RidgePredictor` / `ElasticNetPredictor`, sklearn `Pipeline`, scaler fit inside `fit()` | ✅ | `forecasting/linear.py` — `ridge` / `elasticnet` `BasePredictor` subclasses over the full point-in-time feature frame; next-return target rebuilt to a close; imputer+scaler fit inside the `Pipeline`; feature schema pinned at fit; instrument + label-boundary guards mirror `drift`; 8 round-trip/guard tests |
| B8 | `trees.py`: `GradientBoostingPredictor` (`HistGradientBoostingRegressor`) | ✅ | `forecasting/trees.py` — `gradient_boosting` `BasePredictor` over the full point-in-time feature frame, sharing `_frame_model.FrameModelPredictor` with `linear.py` (no imputer/scaler stage; HGB handles NaNs natively). 8 round-trip/guard tests mirroring `test_linear.py` |
| B9 | `deep.py`: `LstmPredictor` (PyTorch), guarded soft import, registration skipped if extra absent | ✅ | `forecasting/deep.py` — `lstm` `FrameModelPredictor` subclass (median imputer → sklearn-wrapped `nn.LSTM` over the last `lookback` rows). torch soft-imported; when absent the module imports, `LSTM_AVAILABLE=False`, and nothing registers (`get_predictor_class("lstm")` raises). Shares B7/B8 target/reconstruction/guards. `test_deep.py`: 1 unconditional registration test + a torch-gated round-trip/guard class (6 skipped without the extra). Also `modeling/deep.py` `lstm` estimator (registers `available=False` when absent) |
| B10 | `PredictionModel` model (`key`/`params`/`instruments`/`artifact_path`/`metrics`/`is_active`, `clean()` validates key) + migration | ✅ | Delivered as `modeling.TradingModel` (+`ModelTrainingRun`), superset; `clean()` validates estimator key + feature/target specs |
| B11 | `Prediction` model (audit row, `actual_close` nullable, unique `(model, instrument, target_date)`) + migration | ✅ | Delivered as `modeling.ModelPrediction` — same shape (`actual_value`/`abs_error` nullable, unique `(model, instrument, target_date)`) |
| B12 | `services.make_prediction()` (only writer of `Prediction`) + `backfill_actuals()` | ✅ | `modeling.prediction.predict` (sole `ModelPrediction` writer) + `backfill_actuals()` |
| B13 | `management/commands/predict_price.py` (`SYMBOL MODEL_KEY --as-of --params`) | ✅ | `modeling` `predict_model <ID> <SYMBOL> --as-of [--target-date]` |
| B14 | `management/commands/train_predictor.py` (`MODEL_ID --start --end`) → `artifact_path` | ✅ | `modeling` `train_model <ID> [--start --end]` → joblib artifact under `MODEL_ARTIFACT_DIR` |
| B15 | `forecasting.tasks.run_daily_predictions` Celery task (unscheduled) | ✅ | `modeling.tasks.run_model_predictions` (+ `train_model_task`, `backfill_prediction_actuals`), unscheduled |
| B16 | Predictor round-trip tests (`predict_series` length == input; each model fits + predicts) | 🟡 | `forecasting` baseline + statistical + linear + tree coverage done (54 tests); LSTM round-trip/guard tests exist (`test_deep.py::TestWithTorch`) but run only where the `torch` extra is installed — skipped in this repo's env; `modeling` has 60 tests (every estimator fits+predicts) |
| B17 | `forecasting` admin registrations | ✅ | `modeling/admin.py` registers `TradingModel`/`ModelTrainingRun`/`ModelPrediction`; `forecasting` still has no models to register |

## Phase C — leakage-safe walk-forward backtesting

Delivered as the standalone **`backtesting` app** over `modeling.TradingModel`
(routed `/backtests/`), rather than inside `forecasting`. Full UI + admin +
`backtest_model` command + unscheduled Celery tasks. 44 tests. See
`docs/BACKTESTING.md`. A `Backtest` runs in one of two `fit_mode`s:
`walk_forward` (retrain each fold, the original C-phase behaviour) or
`frozen_artifact` (score a `modeling`-trained joblib artifact, latest or a
pinned `training_run`, over every session after `trained_at`).

| # | Task | Status | Notes |
|---|------|--------|-------|
| C1 | `backtesting/walkforward.py`: `walk_forward()` expanding/rolling schemes, fresh predictor per fold | ✅ | `generate_folds()` (pure) + `engine.run_backtest` builds a fresh `modeling.training.build_pipeline` per fold |
| C2 | Enforce `max(train.index) < min(test.index)` with a gap; assert on every fold | ✅ | `generate_folds` asserts `train_end < test_start`; `engine` also drops train rows whose label wasn't observable before the fold's first test decision |
| C3 | `backtesting/metrics.py`: MAE/RMSE/MAPE/R², directional accuracy, skill-vs-naive, trading translation | ✅ | Accuracy reuses `modeling.metrics`; `metrics.positions_from_forecast` + `simulate_instrument` + `combine_equity_curves` do the trade translation |
| C4 | `WalkForwardResult`: per-fold table + aggregate + predicted-vs-actual & equity series | ✅ | `BacktestRun.metrics` (accuracy + trading) + `equity_curve`; `BacktestFold` / `BacktestPrediction` / `BacktestTrade` rows; detail page renders all of it |
| C5 | Leak canary test: future-peeking predictor is flagged by the harness | ✅ | `test_engine.py::test_naive_baseline_is_beatable_reference` (naive skill-vs-naive ~= 0); `test_leakage.py` availability asserts |
| C6 | Leak canary test: future-dated headline does not change a feature bundle | ✅ | Covered upstream by `research`/`modeling` point-in-time tests; `backtesting` inherits `build_dataset` |
| C7 | Leak canary test: train/test index disjointness over random fold configs | ✅ | `test_walkforward.py::test_train_always_before_test_with_gap` (20 randomised configs) |
| C8 | `management/commands/backtest_predictor.py` (…) | ✅ | `backtesting` `backtest_model <ID> [--fit-mode --training-run --scheme --train-span --test-span --step --gap --start --end]` |
| C9 | `BacktestRun` model + migration (stores params + results JSON for the UI) | ✅ | `backtesting/migrations/0001_initial.py` — `Backtest` + `BacktestRun` + `BacktestFold` + `BacktestPrediction` + `BacktestTrade`; `0002` adds `fit_mode` + `training_run` FK |
| C10 | End-to-end test: `naive` vs `ridge` walk-forward on fixture data; skill score computed | ✅ | `test_engine.py` — both run to `success`, `skill_vs_naive` in aggregate metrics |
| C11 | `frozen_artifact` fit mode: backtest a `modeling`-trained artifact without retraining | ✅ | `engine._score_frozen` — `joblib.load` latest/pinned artifact, feature/target-spec guard, score sessions strictly after `trained_at` as one pseudo-fold; `test_frozen.py` (5 tests) |

## Phase D — `dashboard` app (web UI)

The initial PSX viewer lives in `marketdata` and uses Django templates, CSS and SVG.
It provides a foundation for D1-D3 and D9-D10; the full forecasting dashboard,
HTMX/Plotly integration and its remaining pages/tests are still pending.

| # | Task | Status | Notes |
|---|------|--------|-------|
| D0 | PSX daily-data viewer with database persistence | ✅ | Fetch/save with upserts, saved-symbol navigation, date filters, SVG close chart, paginated OHLCV, CSV export, authentication and import permission; 25 market-data tests pass |
| D1 | Create `dashboard` app; add `django-htmx` (middleware); base template with Tailwind + vendored Plotly | 🟡 | PSX viewer foundation complete in marketdata; full forecasting dashboard scope pending |
| D2 | Instruments page — searchable table, last close, last prediction vs actual | 🟡 | PSX viewer foundation complete in marketdata; full forecasting dashboard scope pending |
| D3 | Symbol detail — Plotly candlestick + volume; HTMX indicator overlay toggles | 🟡 | PSX viewer foundation complete in marketdata; full forecasting dashboard scope pending |
| D4 | Symbol detail — latest-forecast panel (predicted close, interval, model, confidence) | ⬜ | |
| D5 | Symbol detail — news headlines + sentiment chips; social/fundamentals "not configured" panels | ⬜ | |
| D6 | Predictors page — registry catalogue (key, trainable, available) + configured models + last metrics | ✅ | `modeling` `/modeling/estimators/` (catalogue: key/task/available/params) + `/modeling/` (configured models + last holdout metric) |
| D7 | Backtest runner — form → HTMX POST → per-fold table, skill badge, predicted-vs-actual chart, equity curve; persist `BacktestRun` | ⬜ | |
| D8 | Accuracy leaderboard — rank active models by rolling MAE / directional acc / skill score | ⬜ | |
| D9 | Wire `dashboard` URLs; `login_required` on all views; nav | 🟡 | PSX viewer foundation complete in marketdata; full forecasting dashboard scope pending |
| D10 | View tests (auth required; pages render with fixture data) | 🟡 | PSX viewer foundation complete in marketdata; full forecasting dashboard scope pending |

## Phase E — API, wiring, docs

| # | Task | Status | Notes |
|---|------|--------|-------|
| E1 | DRF read viewsets: `Prediction`, `BacktestRun`, `ResearchSnapshot`, `NewsItem`; `PredictionModel` (`is_active`-only writable) | ⬜ | |
| E2 | `requirements.txt`: `scikit-learn`, `statsmodels`, `pandas-ta`, `vaderSentiment`, `feedparser`, `django-htmx`, `plotly` | 🟡 | `scikit-learn`, `statsmodels`, `vaderSentiment`, `feedparser` present; `pandas-ta`/`django-htmx`/`plotly` still pending (dashboard) |
| E3 | `requirements-ml.txt`: `torch` (+ `docs/DEPLOYMENT.md` note) | 🟡 | `requirements-ml.txt` created (`torch`, used only by `modeling` `lstm`); `docs/DEPLOYMENT.md` note still ⬜ |
| E4 | Update `docs/PLAN.md` — add Phase 7 summary | ✅ | Phase 7 summary already present |
| E5 | Update `CLAUDE.md` — per-app breakdown for `research` / `forecasting` / `dashboard` | 🟡 | Forecasting foundation documented in `40b4265`; complete app breakdowns as remaining phases land |
| E6 | Update `docs/DEPLOYMENT.md` — new deps, model-artifact storage, `sync_research` + `run_daily_predictions` schedules | ⬜ | |
| E7 | Update auto-memory `project-direction` note | ⬜ | |
| E8 | Full green: `manage.py check`, `pytest`, `black`/`isort`/`ruff`, CI | 🟡 | B1–B6 local checks passed; 144 tests green; remote CI and final-phase verification pending |

---

## Changelog

- 2026-09-05 — Plan + task list created (`docs/FORECASTING_PLAN.md`, this file).
- 2026-09-05 — Phase A (`research` app) implemented: `FeatureProvider` interface +
  registry, technical-indicator library, RSS news + VADER sentiment, fundamentals/social
  stubs behind the interface, `ResearchSnapshot` point-in-time cache, `sync_research`
  command, Celery tasks, admin, 12 tests (incl. leak canaries). Suite 100 → 112 green.

- 2026-09-05 - Phase B foundation (B1-B5) complete: predictor registry,
  label-separated frames, completed-day feature assembly, naive/drift baselines.
  Date-only fundamentals now wait until the following day. 21 new tests; full
  suite 133 passing; Django checks and migration checks clean. See
  `docs/FORECASTING.md` for usage, timing assumptions and remaining limitations.

- 2026-09-05 — Recorded foundation commit `40b4265`, reconciled partial
  testing/documentation statuses, and identified B6 as the next task.

- 2026-09-05 - B6 complete: SARIMA/ETS predictors, statsmodels dependency, replay and leakage-boundary tests. Next: B7 (Ridge/ElasticNet).

- 2026-09-05 - B7 complete: `forecasting/linear.py` adds `ridge` / `elasticnet`
  `BasePredictor` subclasses. They consume the full point-in-time feature frame
  (price lags/returns + research bundles), fit an sklearn `Pipeline`
  (median `SimpleImputer(keep_empty_features=True)` -> `StandardScaler` ->
  `Ridge`/`ElasticNet`) on a next-session simple-return target, and rebuild the
  forecast as `close * (1 + predicted_return)` so a zero signal reproduces the
  naive baseline. Feature schema is pinned at fit; instrument and label-boundary
  guards mirror `drift`; failed refits clear state. 8 new round-trip/guard tests
  (17 parametrised cases). Full suite 230 passing; Django + migration checks,
  black, isort, ruff clean. Next: B8 (`GradientBoostingPredictor`).

- 2026-09-05 - New `modeling` app added (separate from the strict `forecasting`
  path): a UI-driven studio where an operator configures an estimator + a
  feature spec + a target spec, trains it (joblib artifact + train/holdout
  metrics + skill-vs-naive), and predicts (persisted `ModelPrediction` with
  actual-value backfill). Covers sklearn linear / trees / MLP + trivial
  baselines, an optional torch `lstm` (`requirements-ml.txt`), and target
  types horizon close/return, direction, weekday-anchored (Mon->Fri) and
  multi-step. Reuses `research` technical indicators and `strategies` signals
  as candidate inputs. Adds `scikit-learn` to `requirements.txt` and
  `MODEL_ARTIFACT_DIR`. This effectively implements the configurable-model +
  persistence intent of B10-B17 / D6; the `forecasting` B-tasks remain the
  leakage-strict next-day-close predictors and walk-forward (Phase C).
  60 new tests. See `docs/MODELING.md`.

Validation: 213 tests passing; Django check, migration check, black, isort and ruff clean.

- 2026-09-05 - Web UI: added a shared app menubar to `marketdata/base.html`
  (Market Data / Backtesting / Modeling / Admin / API) with active-section
  highlighting via `request.resolver_match.app_name`; styles in
  `marketdata/static/marketdata/dashboard.css`, gated on authentication.
  4 new tests (`marketdata/tests/test_nav.py`); suite green.

- 2026-09-05 - B8 complete: `forecasting/trees.py` adds the `gradient_boosting`
  `BasePredictor` (`HistGradientBoostingRegressor`) over the full point-in-time
  feature frame. The shared fit/predict/leakage-guard machinery from
  `linear.py` was extracted to `forecasting/_frame_model.py::FrameModelPredictor`;
  `_LinearPredictor` now only overrides `_build_pipeline` to add the
  imputer+scaler stage, while the tree predictor uses the default pipeline
  (HGB handles NaNs natively, no scaling needed). Same next-return target,
  `close * (1 + r)` reconstruction, pinned schema / instrument / `fitted_through`
  guards and failed-refit clearing. `random_state` pinned by default.
  8 new tests (`test_trees.py`) mirroring `test_linear.py` plus a NaN-tolerance
  case. `forecasting` suite 53 passing; Django check, black, isort, ruff clean.
  Next: B9 (optional PyTorch LSTM). Informed by the knowledge-base pattern
  `ml/configurable-model-training.md`.

- 2026-09-05 - Phase C complete: new `backtesting` app - walk-forward
  retrain/score of a `modeling.TradingModel` + forecast->trade->equity
  translation. Pure `walkforward.generate_folds` (expanding/rolling, `gap`
  embargo, `train_end < test_start` asserted), `engine.run_backtest`
  (never-raises, reuses `modeling.dataset`/`training`/`metrics` and
  `strategies...BacktestResult`), 5 models, full `/backtests/` UI, admin,
  `backtest_model` command, unscheduled tasks. Routed `/backtests/`
  (`/backtesting/` stays the strategies UI). 39 new tests; full suite
  269 passing; check + black/isort/ruff clean. See `docs/BACKTESTING.md`.

- 2026-09-06 - B9 complete: `forecasting/deep.py` adds the optional `lstm`
  predictor. `torch` is soft-imported from `requirements-ml.txt`; when it is
  absent the module imports cleanly, `LSTM_AVAILABLE` is `False` and **nothing
  registers** (`get_predictor_class("lstm")` raises) — no other part of the
  app or suite depends on torch. When present, `LstmPredictor` is a
  `FrameModelPredictor` subclass sharing the B7/B8 contract (next-return
  target, `close * (1 + r)` reconstruction, pinned schema / instrument /
  `fitted_through` guards, failed-refit clearing, unset intervals); its
  pipeline is a median `SimpleImputer(keep_empty_features=True)` → a small
  sklearn-wrapped `nn.LSTM` that standardises internally and reads the last
  `lookback` feature rows (causal left-padding, no retained training tail —
  documented). `apps.ready()` imports `deep`; `requirements-ml.txt` comment
  now covers both LSTM models. `test_deep.py`: 1 unconditional
  registration-tracks-torch test + a `torch`-gated round-trip/guard class
  (6 skipped in this env). `forecasting` 54 passed / 6 skipped; full suite
  283 passed / 6 skipped; black/isort/ruff + Django check clean. Informed by
  the knowledge-base pattern `ml/configurable-model-training.md` (optional
  heavy dep stays optional; registry over import paths).

- 2026-09-06 - `backtesting` gains a `frozen_artifact` fit mode (C11):
  `Backtest.fit_mode` (`walk_forward` default) + optional `training_run` FK
  (migration `0002`). `engine._execute` picks `_score_walk_forward` (the
  existing per-fold retrain, refactored out) or `_score_frozen`, which
  `joblib.load`s the model's stored artifact (latest or the pinned run),
  asserts `feature_names`/`target_spec` still match, and scores every session
  strictly after the artifact's `trained_at` local date as one pseudo-fold.
  Shared forecast->position->equity tail unchanged. Form / admin /
  `backtest_model --fit-mode --training-run` / detail page updated. 5 new
  tests (`test_frozen.py`); full suite 282 passing; black/isort/ruff clean.
  Informed by `ml/configurable-model-training.md` (artifact feature-name
  guard, never-raise entry point).

- 2026-09-06 - `frozen_artifact` fix: a frozen backtest on a real
  `modeling`-trained model always failed ("0 sessions after the artifact was
  trained") - it gated on the wall-clock `trained_at` *and* capped the scoring
  dataset at `model.train_end`, so nothing was left out-of-sample. Now
  `modeling.training` records `train_start`/`train_end` in the artifact, and
  `engine._score_frozen` uses `min(trained_at, train_end)` as the boundary
  (old artifacts fall back to the live `TradingModel.train_end`) while
  `_execute` builds the frozen scoring dataset out to today. Detail/index/form
  UI reworked for the two fit modes (per-mode config panel, failure banner,
  fit-mode column, grouped form sections). test_frozen fixtures made realistic
  (history ends today, past `train_end`); +1 fallback test; full suite 285
  passing; black/ruff clean.

- 2026-09-06 - Web UI shell landed (committed): the shared authenticated
  menubar in `marketdata/base.html` (Market Data / Backtesting / Modeling /
  Admin / API, active section via `resolver_match.app_name`) plus a
  `strategies` backtesting page at `/backtesting/`. The page replays a rule
  strategy - or a saved `Strategy` with `view_strategy` permission - over
  stored daily `PriceBar`s for one instrument and renders an equity curve,
  performance stats and a trade ledger with CSV export.
  `strategies.backtesting.engine.run_backtest` gained `next_open` (fill at
  the following bar's open; final-bar signals unfilled), `commission_bps` /
  `slippage_bps` (cost per fill, on `Trade.fees`, netted from `Trade.pnl`),
  input guards, and drawdown measured from `initial_cash`. 13 new tests
  (`strategies/tests/test_views.py` + engine guard/cost/timing cases,
  `marketdata/tests/test_nav.py`); full suite 298 passed, 6 skipped;
  black/isort/ruff + Django check clean. Still separate from the pending
  forecasting dashboard (D1-D10).
