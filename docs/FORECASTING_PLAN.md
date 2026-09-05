# Next-Day Close Forecasting — Build-Out Plan

Extends `docs/PLAN.md`. This is **Phase 7** of the project: a pluggable
next-day closing-price forecasting layer, a leakage-safe walk-forward
backtester to validate it, an external-signal/feature library, and a
server-rendered web UI to drive all of it.

## Goals (from the request)

1. A **predictor** ("agent") that forecasts the **next trading day's closing
   price** for any PSX stock.
2. **More than one predictor**, user-selectable and independently testable
   from the UI.
3. **Backtesting on past data with no look-ahead / data leakage**, so a good
   backtest score is evidence the model will work going forward.
4. Market-agnostic by construction — **PSX only today**, other exchanges
   drop in later without a rewrite.
5. A **feature/signal library** pulling from price history, technical
   indicators, company fundamentals, news, and social media — all
   **point-in-time correct**.
6. **Technical indicators** available as first-class features.
7. A **web app with a good UI** (not just Django admin).
8. A **task list with status** that is kept updated as work lands
   (`docs/TASKS.md`).

## Decisions (confirmed with the user, 2026-09-05)

- **UI stack**: Django server-rendered + `django-htmx` + Tailwind + Plotly.
  One codebase, no Node build in the deploy path. Reuses the DRF API for
  data where convenient.
- **ML dependencies**: light models are **core** (`scikit-learn`,
  `statsmodels`); a deep-learning predictor (PyTorch LSTM/GRU) ships as an
  **optional extra** (`requirements-ml.txt`), its predictor module guarded
  by a soft import so the app runs without torch installed.
- **External data**: ship the `FeatureProvider` interface with a strict
  point-in-time contract now. **Working now**: technical indicators, RSS
  news ingestion + VADER sentiment. **Stubbed behind the interface** with
  explicit TODOs: social-media signals, company fundamentals (need API
  keys / paid feeds / fragile scraping — deferred, not designed out).
- **Scope of the current chunk**: write these docs + the task list, wire
  `PLAN.md`/`CLAUDE.md`, then implement **Phase A** (the `research` app).

---

## New apps

| App         | Responsibility |
|-------------|----------------|
| `research`  | Feature/signal extraction. `FeatureProvider` interface; `technical`, `fundamentals`, `news`, `social` providers; `ResearchSnapshot` cache for reproducible, point-in-time feature bundles. |
| `forecasting` | `BasePredictor` framework + registry (mirrors `strategies/registry.py`), `PredictionModel` / `Prediction` DB models, concrete predictors, feature assembly, walk-forward backtester, daily-prediction Celery task + management commands. |
| `dashboard` | Django + HTMX + Tailwind + Plotly web UI: instruments, symbol detail (price + indicators + latest forecast + news/sentiment), predictor catalogue, backtest runner, accuracy leaderboard. |

All three follow the conventions already in the repo: register in
`INSTALLED_APPS`, wire URLs via `include()`, one interface + a registry so
concrete implementations are swappable, `apps.ready()` imports concrete
modules so decorators fire, providers isolate third-party libraries.

---

## Phase A — `research` app: feature / signal library

**Interface & point-in-time contract**
- `research/providers/base.py`: `FeatureProvider` ABC —
  `get_features(symbol: str, as_of: datetime, *, exchange="PSX") -> dict[str, float]`.
  Hard rule, enforced by tests: a provider may only use information that
  was **publicly available at or before `as_of`**. No provider ever reads a
  bar/headline/report dated after `as_of`.
- `FeatureBundle` dataclass: `{namespace.name: value}` flat float map +
  `as_of` + `sources` (citations), so a bundle is self-describing and
  reproducible.

**Providers**
- `technical.py` — indicator library over `marketdata.PriceBar` history:
  SMA/EMA (multiple windows), RSI, MACD (line/signal/hist), Bollinger
  band position/width, ATR, stochastic %K/%D, OBV slope, ROC/momentum,
  realized volatility, volume z-score, gap. Vectorized with `pandas`;
  optional `pandas-ta` acceleration behind a soft import with a pure-pandas
  fallback. Unit tests check values against hand-computed fixtures.
- `news.py` — **working**. `feedparser`-based RSS ingestion (configurable
  feed list per exchange), `NewsItem` model (`symbol`, `headline`, `url`,
  `published_at`, `source`, `sentiment`), VADER sentiment
  (`vaderSentiment`). Idempotent re-ingestion keyed on URL hash (per the
  knowledge-base "Chunking & embedding ingestion" pattern — idempotent
  ingest + source citation; a vector index over article bodies is a noted
  later extension). Features: rolling headline count, mean/last sentiment,
  sentiment trend, all windowed strictly before `as_of`.
- `fundamentals.py` — **stub behind the interface**. `CompanyFundamental`
  model (`symbol`, `as_of_report_date`, ratios JSON). `get_features`
  returns the latest report with `as_of_report_date <= as_of` or `{}`.
  One manual/CSV loader; live scraping is a TODO.
- `social.py` — **stub behind the interface**. `SocialMention` model
  (`symbol`, `platform`, `posted_at`, `sentiment`, `reach`). Interface +
  a fixture loader; live X/Reddit/StockTwits integrations are TODOs
  requiring credentials.

**Aggregation & cache**
- `research/services.py`: `build_feature_bundle(symbol, as_of, providers=…)`
  merges all provider outputs into one `FeatureBundle`.
- `ResearchSnapshot` model: persists a bundle for `(symbol, as_of)` so
  backtests and the daily prediction job read identical, frozen inputs.
  `get_or_build` upserts.
- `management/commands/sync_research.py`:
  `sync_research [--symbol X] [--as-of YYYY-MM-DD]`.
- Celery task `research.tasks.sync_all_research` (unscheduled, same caveat
  as the other tasks — a `PeriodicTask` is added at deploy time).

**Exit check**: `sync_research --symbol <sym>` writes a `ResearchSnapshot`;
technical features match fixtures; a test that feeds a post-`as_of` headline
asserts it is excluded.

---

## Phase B — `forecasting` app: predictor framework

**Interface**
- `forecasting/base.py`: `BasePredictor` ABC.
  - `fit(history: TrainingFrame) -> None` (no-op for stateless models).
  - `predict_next(symbol, as_of, *, exchange="PSX") -> PricePrediction` —
    the next session's close after `as_of`.
  - `predict_series(frame) -> list[PricePrediction]` — one prediction per
    row, for backtest replay (mirrors `BaseStrategy.generate_signals`).
- `PricePrediction` dataclass: `target_date`, `predicted_close`,
  `lower`/`upper` (interval, optional), `confidence`, `model_key`,
  `features_hash`.
- `forecasting/registry.py`: `@register_predictor("key")` /
  `get_predictor_class(key)` / `registered_keys()` — copied structure from
  `strategies/registry.py`.
- `forecasting/features.py`: `assemble_training_frame(symbol, start, end)` —
  joins `PriceBar` lag/return features with `research` feature bundles as of
  **each bar's own date**, target = next bar's close. This is the single
  choke point where point-in-time correctness is guaranteed.

**Predictors** (each `@register_predictor`)
- `naive.py` — `NaiveClosePredictor` (tomorrow = today), `DriftPredictor`
  (random-walk-with-drift). Baselines every other model must beat.
- `stats.py` — `SarimaPredictor`, `EtsPredictor` (`statsmodels`),
  refit per fold on the training slice only.
- `linear.py` — `RidgePredictor` / `ElasticNetPredictor` on lagged returns
  + technical + news features; `sklearn` `Pipeline` with the scaler **fit
  inside `fit()`** only.
- `trees.py` — `GradientBoostingPredictor` (`sklearn`
  `HistGradientBoostingRegressor`).
- `deep.py` — `LstmPredictor` (PyTorch). Module top guarded by
  `try: import torch except ImportError`; registering is skipped and the UI
  shows it as unavailable when the extra isn't installed.

**Persistence**
- `PredictionModel` — a configured predictor instance: `key`, `params`
  JSON, `instruments` M2M, `artifact_path` (joblib/torch dump of a fitted
  model), `trained_at`, `metrics` JSON, `is_active`. `key` validity checked
  in `clean()` (same pattern as `strategies.Strategy`).
- `Prediction` — audit row: `model` FK, `instrument` FK, `made_at`,
  `as_of`, `target_date`, `predicted_close`, `lower`/`upper`,
  `actual_close` (nullable — backfilled when the real bar lands),
  `features_hash`. Unique on `(model, instrument, target_date)`.
- `forecasting/services.py`:
  `make_prediction(model, instrument, as_of=None)` — the only path that
  writes a `Prediction`; `backfill_actuals()` — fills `actual_close` from
  `PriceBar` and is what the accuracy leaderboard reads.

**Commands & tasks**
- `predict_price SYMBOL MODEL_KEY [--as-of] [--params '{...}']`.
- `train_predictor MODEL_ID [--start] [--end]` — fits and writes
  `artifact_path`.
- Celery task `forecasting.tasks.run_daily_predictions` — after PSX close,
  for each active `PredictionModel` × instrument, call `make_prediction`;
  then `backfill_actuals`. Unscheduled (deploy-time `PeriodicTask`).

**Exit check**: `predict_price <sym> ridge` prints a number and writes a
`Prediction`; `train_predictor` produces a loadable artifact; every
predictor round-trips through `predict_series` with length == input.

---

## Phase C — leakage-safe walk-forward backtesting

`forecasting/backtesting/walkforward.py`:
`walk_forward(predictor_factory, symbol, start, end, *, scheme="expanding",
train_span, test_span, step, min_train)`.

**Anti-leakage design — enforced, not just documented**
- Folds are contiguous and ordered; for every fold
  `assert max(train.index) < min(test.index)` (a gap of ≥1 bar).
- A **fresh predictor instance per fold**; `fit()` sees only that fold's
  training slice. No object, scaler, imputer, or encoder is reused across
  the train/test boundary.
- Every feature is drawn from `research`/`features.py`, which only ever
  reads data `<= as_of`; the harness passes each test row's own date as
  `as_of`.
- Target for row *t* is the close of row *t+1*; the harness never hands a
  predictor a frame that includes the target bar.
- No full-series normalization, no `shuffle`, no k-fold — time order is
  never broken.
- **Leak canaries** (tests): (a) a predictor that peeks at `t+1` is
  detected by a monotonic-error / perfect-fit check and the test asserts
  the harness flags it; (b) injecting a future-dated headline into
  `research` and asserting the resulting feature bundle is unchanged;
  (c) asserting train/test index disjointness on random fold configs.

**Metrics** (`forecasting/backtesting/metrics.py`)
- Regression: MAE, RMSE, MAPE, R².
- Directional accuracy (sign of predicted vs actual next-day return).
- **Skill score** vs the naive baseline (`1 - model_err / naive_err`) —
  the headline number: positive means it genuinely beats random walk.
- Trading translation: cumulative return of "long if predicted up" with
  costs, plus hit rate — reuses `BacktestResult`-style stats so it lines
  up with the existing strategy backtester.
- `WalkForwardResult`: per-fold table + aggregate + the
  predicted-vs-actual and equity series for the UI.

- `management/commands/backtest_predictor.py`:
  `backtest_predictor SYMBOL MODEL_KEY --start --end [--scheme] [--train-span]
  [--test-span] [--step] [--params]` — prints the metrics table.
- `BacktestRun` model (optional, for the UI): stores a run's params +
  results JSON so the dashboard can list history.

**Exit check**: `backtest_predictor <sym> naive` and `... ridge` both run;
ridge's skill score is reported; the three leak-canary tests pass; a
deliberately leaky predictor is flagged.

---

## Phase D — `dashboard` app: the web UI

Django + `django-htmx` + Tailwind (via CDN in dev, `django-tailwind` or a
vendored build for prod) + Plotly (vendored JS). Session-auth, all views
`login_required`.

**Pages**
- **Instruments** — searchable table (symbol, name, sector, last close,
  last prediction vs actual).
- **Symbol detail** — Plotly candlestick + volume; indicator overlays
  toggled via HTMX; panel with the latest forecast (predicted close,
  interval, which model, confidence); recent news headlines with sentiment
  chips; social/fundamentals panels render "not configured yet" from the
  stubs.
- **Predictors** — catalogue from the registry: key, description, whether
  trainable, whether available (torch extra), configured `PredictionModel`
  instances and their last metrics.
- **Backtest runner** — form (symbol, predictor, date range, scheme,
  windows, params JSON) → HTMX POST → results: per-fold metrics table,
  skill score badge, predicted-vs-actual chart, equity curve. Persists a
  `BacktestRun`.
- **Accuracy leaderboard** — ranks active `PredictionModel`s by rolling
  MAE / directional accuracy / skill score from `Prediction` rows with
  `actual_close` filled in.

**Exit check**: from a clean DB with synced data, a user can pick a symbol,
see a forecast and news, run a backtest, and read its skill score — all in
the browser, no admin.

---

## Phase E — API, wiring, docs

- DRF: read-only `PredictionViewSet`, `BacktestRunViewSet`,
  `ResearchSnapshotViewSet`, `NewsItemViewSet`; `PredictionModelViewSet`
  writable only for `is_active` (same shape as `StrategyViewSet`). Owner
  scoping where a user dimension applies; reference data open to any
  authenticated user.
- `requirements.txt`: add `scikit-learn`, `statsmodels`, `pandas-ta`
  (optional-accelerator, soft-imported), `vaderSentiment`, `feedparser`,
  `django-htmx`, `plotly`. New `requirements-ml.txt`: `torch` (+ note in
  `docs/DEPLOYMENT.md`).
- Update `docs/PLAN.md` (add Phase 7 summary), `CLAUDE.md` (per-app
  breakdown for `research` / `forecasting` / `dashboard`),
  `docs/DEPLOYMENT.md` (new deps, model-artifact storage location, two new
  scheduled jobs: `sync_research`, `run_daily_predictions`).
- Update the auto-memory `project-direction` note when phases land.

**Exit check**: `python manage.py check` clean; `pytest` green;
`black . && isort . && ruff check .` clean; CI passes.

---

## Suggested execution order

A (features) → B (predictors, needs A) → C (backtester, needs B) →
D (UI, needs C for the runner) → E (polish). Each phase is independently
shippable and testable, matching the rest of the repo.

## Knowledge base

- **Chunking & embedding ingestion** (`rag/…`) informs `research/news.py`:
  idempotent re-ingestion keyed on a content hash, source citations kept on
  every item. A vector index over article bodies for semantic news recall
  is a noted later extension, not in this phase.
- **Stateful agentic run lifecycle** informs the daily-prediction task
  shape (deliberate termination, per-item failure isolation) — already the
  pattern used by `execution.tasks.run_trading_cycle`, mirrored here.
- No existing pattern covers walk-forward time-series validation; if the
  leak-canary approach here proves useful, propose it back as a new
  `evaluation/` pattern file.
