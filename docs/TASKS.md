# Task List — Phase 7: Next-Day Close Forecasting

Living checklist for `docs/FORECASTING_PLAN.md`. **Keep this updated as work
lands** — flip status, add notes, check boxes in the same commit as the
change.

Status legend: ⬜ Not started · 🟡 In progress · ✅ Done · ⛔ Blocked · ⏭️ Deferred

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

## Phase B — `forecasting` app (predictor framework)

| # | Task | Status | Notes |
|---|------|--------|-------|
| B1 | Create `forecasting` app; register; `apps.ready()` imports predictor modules | ⬜ | |
| B2 | `base.py`: `BasePredictor` ABC (`fit`/`predict_next`/`predict_series`) + `PricePrediction` dataclass | ⬜ | |
| B3 | `registry.py`: `@register_predictor` / `get_predictor_class` / `registered_keys` | ⬜ | mirror `strategies/registry.py` |
| B4 | `features.py`: `assemble_training_frame()` — lag/return features + `research` bundle as-of each bar; target = next close | ⬜ | point-in-time choke point |
| B5 | `naive.py`: `NaiveClosePredictor`, `DriftPredictor` (baselines) | ⬜ | |
| B6 | `stats.py`: `SarimaPredictor`, `EtsPredictor` (`statsmodels`), refit per fold | ⬜ | |
| B7 | `linear.py`: `RidgePredictor` / `ElasticNetPredictor`, sklearn `Pipeline`, scaler fit inside `fit()` | ⬜ | |
| B8 | `trees.py`: `GradientBoostingPredictor` (`HistGradientBoostingRegressor`) | ⬜ | |
| B9 | `deep.py`: `LstmPredictor` (PyTorch), guarded soft import, registration skipped if extra absent | ⬜ | `requirements-ml.txt` |
| B10 | `PredictionModel` model (`key`/`params`/`instruments`/`artifact_path`/`metrics`/`is_active`, `clean()` validates key) + migration | ⬜ | |
| B11 | `Prediction` model (audit row, `actual_close` nullable, unique `(model, instrument, target_date)`) + migration | ⬜ | |
| B12 | `services.make_prediction()` (only writer of `Prediction`) + `backfill_actuals()` | ⬜ | |
| B13 | `management/commands/predict_price.py` (`SYMBOL MODEL_KEY --as-of --params`) | ⬜ | |
| B14 | `management/commands/train_predictor.py` (`MODEL_ID --start --end`) → `artifact_path` | ⬜ | |
| B15 | `forecasting.tasks.run_daily_predictions` Celery task (unscheduled) | ⬜ | |
| B16 | Predictor round-trip tests (`predict_series` length == input; each model fits + predicts) | ⬜ | |
| B17 | `forecasting` admin registrations | ⬜ | |

## Phase C — leakage-safe walk-forward backtesting

| # | Task | Status | Notes |
|---|------|--------|-------|
| C1 | `backtesting/walkforward.py`: `walk_forward()` expanding/rolling schemes, fresh predictor per fold | ⬜ | |
| C2 | Enforce `max(train.index) < min(test.index)` with a gap; assert on every fold | ⬜ | |
| C3 | `backtesting/metrics.py`: MAE/RMSE/MAPE/R², directional accuracy, skill-vs-naive, trading translation | ⬜ | |
| C4 | `WalkForwardResult`: per-fold table + aggregate + predicted-vs-actual & equity series | ⬜ | |
| C5 | Leak canary test: future-peeking predictor is flagged by the harness | ⬜ | |
| C6 | Leak canary test: future-dated headline does not change a feature bundle | ⬜ | |
| C7 | Leak canary test: train/test index disjointness over random fold configs | ⬜ | |
| C8 | `management/commands/backtest_predictor.py` (`SYMBOL MODEL_KEY --start --end --scheme --train-span --test-span --step --params`) | ⬜ | |
| C9 | `BacktestRun` model + migration (stores params + results JSON for the UI) | ⬜ | |
| C10 | End-to-end test: `naive` vs `ridge` walk-forward on fixture data; skill score computed | ⬜ | |

## Phase D — `dashboard` app (web UI)

| # | Task | Status | Notes |
|---|------|--------|-------|
| D1 | Create `dashboard` app; add `django-htmx` (middleware); base template with Tailwind + vendored Plotly | ⬜ | |
| D2 | Instruments page — searchable table, last close, last prediction vs actual | ⬜ | |
| D3 | Symbol detail — Plotly candlestick + volume; HTMX indicator overlay toggles | ⬜ | |
| D4 | Symbol detail — latest-forecast panel (predicted close, interval, model, confidence) | ⬜ | |
| D5 | Symbol detail — news headlines + sentiment chips; social/fundamentals "not configured" panels | ⬜ | |
| D6 | Predictors page — registry catalogue (key, trainable, available) + configured models + last metrics | ⬜ | |
| D7 | Backtest runner — form → HTMX POST → per-fold table, skill badge, predicted-vs-actual chart, equity curve; persist `BacktestRun` | ⬜ | |
| D8 | Accuracy leaderboard — rank active models by rolling MAE / directional acc / skill score | ⬜ | |
| D9 | Wire `dashboard` URLs; `login_required` on all views; nav | ⬜ | |
| D10 | View tests (auth required; pages render with fixture data) | ⬜ | |

## Phase E — API, wiring, docs

| # | Task | Status | Notes |
|---|------|--------|-------|
| E1 | DRF read viewsets: `Prediction`, `BacktestRun`, `ResearchSnapshot`, `NewsItem`; `PredictionModel` (`is_active`-only writable) | ⬜ | |
| E2 | `requirements.txt`: `scikit-learn`, `statsmodels`, `pandas-ta`, `vaderSentiment`, `feedparser`, `django-htmx`, `plotly` | ⬜ | |
| E3 | `requirements-ml.txt`: `torch` (+ `docs/DEPLOYMENT.md` note) | ⬜ | |
| E4 | Update `docs/PLAN.md` — add Phase 7 summary | ⬜ | |
| E5 | Update `CLAUDE.md` — per-app breakdown for `research` / `forecasting` / `dashboard` | ⬜ | |
| E6 | Update `docs/DEPLOYMENT.md` — new deps, model-artifact storage, `sync_research` + `run_daily_predictions` schedules | ⬜ | |
| E7 | Update auto-memory `project-direction` note | ⬜ | |
| E8 | Full green: `manage.py check`, `pytest`, `black`/`isort`/`ruff`, CI | ⬜ | |

---

## Changelog

- 2026-09-05 — Plan + task list created (`docs/FORECASTING_PLAN.md`, this file).
- 2026-09-05 — Phase A (`research` app) implemented: `FeatureProvider` interface +
  registry, technical-indicator library, RSS news + VADER sentiment, fundamentals/social
  stubs behind the interface, `ResearchSnapshot` point-in-time cache, `sync_research`
  command, Celery tasks, admin, 12 tests (incl. leak canaries). Suite 100 → 112 green.
