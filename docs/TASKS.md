# Task List — Phase 7: Next-Day Close Forecasting

Living checklist for `docs/FORECASTING_PLAN.md`. **Keep this updated as work
lands** — flip status, add notes, check boxes in the same commit as the
change.

Status legend: ⬜ Not started · 🟡 In progress · ✅ Done · ⛔ Blocked · ⏭️ Deferred

## Current status (2026-09-05)

- Phase A is complete. Phase B foundation (B1–B5) is committed as `40b4265`.
- Latest validation: **269 tests passed** (45 forecasting + 60 modeling +
  39 backtesting); Django system/migration checks and Black/isort/Ruff checks
  passed locally. Remote CI has not been verified.
- Phase C (walk-forward backtesting) is complete as the standalone
  `backtesting` app over `modeling.TradingModel` — see the Phase C table and
  `docs/BACKTESTING.md`.
- The `modeling` app (commit `11a4bf0`, branch `phase7-modeling-app`)
  delivers the configurable-model + persistence intent as a **parallel app**
  to `forecasting`: covers B10–B15, B17 and D6, and partially B7–B9 / B16 /
  E2 / E3 (see the tables below). It uses sklearn `Pipeline` estimators + a
  single trailing holdout, **not** `forecasting.BasePredictor` prefix-replay
  or walk-forward.
- **Next task for the strict `forecasting` path: B8 — `GradientBoostingPredictor`**
  (`HistGradientBoostingRegressor`), reusing the `forecasting/linear.py`
  fit/predict/guard contract and its round-trip tests, then B9 (optional LSTM)
  and C-phase walk-forward.
- B6 and B7 are complete (`forecasting/linear.py`: `ridge` / `elasticnet`,
  full point-in-time feature frame, next-return target, scaler/imputer fit
  inside the sklearn `Pipeline`). Walk-forward evaluation (Phase C) and the
  forecasting dashboard's forecast panels (D4, D7, D8) remain pending.
- The PSX data viewer is complete: authenticated browsing, fetch-and-save, date
  filters, closing-price chart and CSV export in `marketdata`. Its 25 market-data
  tests pass; live PSX connectivity and remote CI have not been verified.
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
| B8 | `trees.py`: `GradientBoostingPredictor` (`HistGradientBoostingRegressor`) | 🟡 | `modeling` ships `gradient_boosting`/`hist_gbr` estimators; `forecasting.BasePredictor` version still ⬜ |
| B9 | `deep.py`: `LstmPredictor` (PyTorch), guarded soft import, registration skipped if extra absent | 🟡 | `modeling/deep.py` `lstm` — torch soft-imported, registers `available=False` when absent; `forecasting` version still ⬜ |
| B10 | `PredictionModel` model (`key`/`params`/`instruments`/`artifact_path`/`metrics`/`is_active`, `clean()` validates key) + migration | ✅ | Delivered as `modeling.TradingModel` (+`ModelTrainingRun`), superset; `clean()` validates estimator key + feature/target specs |
| B11 | `Prediction` model (audit row, `actual_close` nullable, unique `(model, instrument, target_date)`) + migration | ✅ | Delivered as `modeling.ModelPrediction` — same shape (`actual_value`/`abs_error` nullable, unique `(model, instrument, target_date)`) |
| B12 | `services.make_prediction()` (only writer of `Prediction`) + `backfill_actuals()` | ✅ | `modeling.prediction.predict` (sole `ModelPrediction` writer) + `backfill_actuals()` |
| B13 | `management/commands/predict_price.py` (`SYMBOL MODEL_KEY --as-of --params`) | ✅ | `modeling` `predict_model <ID> <SYMBOL> --as-of [--target-date]` |
| B14 | `management/commands/train_predictor.py` (`MODEL_ID --start --end`) → `artifact_path` | ✅ | `modeling` `train_model <ID> [--start --end]` → joblib artifact under `MODEL_ARTIFACT_DIR` |
| B15 | `forecasting.tasks.run_daily_predictions` Celery task (unscheduled) | ✅ | `modeling.tasks.run_model_predictions` (+ `train_model_task`, `backfill_prediction_actuals`), unscheduled |
| B16 | Predictor round-trip tests (`predict_series` length == input; each model fits + predicts) | 🟡 | `forecasting` baseline + statistical + linear coverage done (45 tests); `modeling` has 60 tests (every estimator fits+predicts); `forecasting` tree/LSTM predictor coverage still pending |
| B17 | `forecasting` admin registrations | ✅ | `modeling/admin.py` registers `TradingModel`/`ModelTrainingRun`/`ModelPrediction`; `forecasting` still has no models to register |

## Phase C — leakage-safe walk-forward backtesting

Delivered as the standalone **`backtesting` app** over `modeling.TradingModel`
(routed `/backtests/`), rather than inside `forecasting`. Full UI + admin +
`backtest_model` command + unscheduled Celery tasks. 39 tests. See
`docs/BACKTESTING.md`.

| # | Task | Status | Notes |
|---|------|--------|-------|
| C1 | `backtesting/walkforward.py`: `walk_forward()` expanding/rolling schemes, fresh predictor per fold | ✅ | `generate_folds()` (pure) + `engine.run_backtest` builds a fresh `modeling.training.build_pipeline` per fold |
| C2 | Enforce `max(train.index) < min(test.index)` with a gap; assert on every fold | ✅ | `generate_folds` asserts `train_end < test_start`; `engine` also drops train rows whose label wasn't observable before the fold's first test decision |
| C3 | `backtesting/metrics.py`: MAE/RMSE/MAPE/R², directional accuracy, skill-vs-naive, trading translation | ✅ | Accuracy reuses `modeling.metrics`; `metrics.positions_from_forecast` + `simulate_instrument` + `combine_equity_curves` do the trade translation |
| C4 | `WalkForwardResult`: per-fold table + aggregate + predicted-vs-actual & equity series | ✅ | `BacktestRun.metrics` (accuracy + trading) + `equity_curve`; `BacktestFold` / `BacktestPrediction` / `BacktestTrade` rows; detail page renders all of it |
| C5 | Leak canary test: future-peeking predictor is flagged by the harness | ✅ | `test_engine.py::test_naive_baseline_is_beatable_reference` (naive skill-vs-naive ~= 0); `test_leakage.py` availability asserts |
| C6 | Leak canary test: future-dated headline does not change a feature bundle | ✅ | Covered upstream by `research`/`modeling` point-in-time tests; `backtesting` inherits `build_dataset` |
| C7 | Leak canary test: train/test index disjointness over random fold configs | ✅ | `test_walkforward.py::test_train_always_before_test_with_gap` (20 randomised configs) |
| C8 | `management/commands/backtest_predictor.py` (…) | ✅ | `backtesting` `backtest_model <ID> [--scheme --train-span --test-span --step --gap --start --end]` |
| C9 | `BacktestRun` model + migration (stores params + results JSON for the UI) | ✅ | `backtesting/migrations/0001_initial.py` — `Backtest` + `BacktestRun` + `BacktestFold` + `BacktestPrediction` + `BacktestTrade` |
| C10 | End-to-end test: `naive` vs `ridge` walk-forward on fixture data; skill score computed | ✅ | `test_engine.py` — both run to `success`, `skill_vs_naive` in aggregate metrics |

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

- 2026-09-05 - Phase C complete: new `backtesting` app - walk-forward
  retrain/score of a `modeling.TradingModel` + forecast->trade->equity
  translation. Pure `walkforward.generate_folds` (expanding/rolling, `gap`
  embargo, `train_end < test_start` asserted), `engine.run_backtest`
  (never-raises, reuses `modeling.dataset`/`training`/`metrics` and
  `strategies...BacktestResult`), 5 models, full `/backtests/` UI, admin,
  `backtest_model` command, unscheduled tasks. Routed `/backtests/`
  (`/backtesting/` stays the strategies UI). 39 new tests; full suite
  269 passing; check + black/isort/ruff clean. See `docs/BACKTESTING.md`.
