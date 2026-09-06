# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

Automated Stock Trading system targeting the Pakistan Stock Exchange (PSX). Being built in
phases per `docs/PLAN.md` (the full approved plan, with rationale):

- **Phase 0 (done)**: project hygiene - settings split, env config, requirements, CI, linting.
- **Phase 1 (done)**: `marketdata` app - PSX data pipeline (see below).
- **Phase 2 (done)**: `strategies` app - pluggable strategy framework + backtesting (see below).
- **Phase 3 (done)**: `portfolio`/`risk`/`execution` apps - paper broker + live trading cycle
  (see below).
- **Phase 4 (done)**: `api` app (DRF) + alerting (see below). Dashboard is Django admin, per
  the plan - no separate frontend was built.
- **Phase 5 (done)**: `Dockerfile` + `docker-compose.yml` + `docs/DEPLOYMENT.md` (see below).
  Docker itself was never available to actually build/run in the environment this was built
  in - review before relying on it.
- **Phase 6 (not started)**: live trading, gated on an actual PSX broker/vendor relationship
  (see docs/PLAN.md) - not just code.
- **Phase 7 (in progress)**: research/forecasting foundation - `research` (feature
  providers), `forecasting` (leakage-strict next-day predictors + walk-forward), the
  parallel `modeling` studio, the `backtesting` walk-forward app, a server-rendered
  operator dashboard ("PSX Observatory"), and Phase 7 DRF read endpoints. See the
  per-app sections below and `docs/FORECASTING.md` / `docs/MODELING.md` /
  `docs/BACKTESTING.md`. Tracked task-by-task on GitHub Projects board #5.

Key direction decisions (see `docs/PLAN.md` for the full rationale):
- Market: PSX. No official free market-data API exists - the plan uses the `psxdata` scraper
  library (pinned to its current alpha release, `psxdata==0.1.0a5`, in requirements.txt).
- PSX has no public self-serve order-routing API either. The `execution` app's
  `BrokerAdapter` interface (Phase 3+) will ship with only a simulated **paper broker**
  implementation until a real vendor/broker relationship is set up - don't assume a live
  PSX broker integration exists or can be trivially added.
- Strategies must go through one pluggable `BaseStrategy` interface supporting rule-based,
  manual-entry, and ML-driven signal sources - not a single hardcoded strategy.
- Paper trading first; live trading is explicitly a later, separate phase.

On Windows, `python`/`pip` may not resolve (Microsoft Store alias stub) - use the `py`
launcher, or the project's own venv directly: `.venv/Scripts/python.exe`.

## Environment setup

```
py -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
cp .env.example .env   # adjust values; defaults work for local sqlite dev
```

`AutomaticStockTrading/settings/` is a package, not a single file:
- `base.py` - shared settings, reads config from env via django-environ (see `.env.example`).
- `dev.py` - local dev (`manage.py` defaults to this via `DJANGO_SETTINGS_MODULE`).
- `prod.py` - production; raises at import time if `SECRET_KEY`/`ALLOWED_HOSTS` aren't
  properly set via env (wsgi.py/asgi.py default to this).

DB defaults to a local sqlite file if `DATABASE_URL` isn't set; set `DATABASE_URL` to a
Postgres URL to match docker-compose/cloud. TIME_ZONE is `Asia/Karachi` (PSX market hours),
not UTC - relevant when scheduling Celery beat tasks.

## Commands

Run from the repo root, using the venv's Python (`.venv/Scripts/python.exe` on Windows, or
activate the venv first):

- Dev server: `python manage.py runserver`
- Migrations: `python manage.py makemigrations` / `python manage.py migrate`
- Superuser: `python manage.py createsuperuser`
- Tests: `pytest` (or `python manage.py test`)
- Lint/format: `black .`, `isort .`, `ruff check .` (all configured in `pyproject.toml`;
  CI in `.github/workflows/ci.yml` runs these plus tests on push/PR)
- Celery worker (once tasks exist): `celery -A AutomaticStockTrading worker -l info`
- Celery beat (once schedules exist): `celery -A AutomaticStockTrading beat -l info`

## Architecture

- `AutomaticStockTrading/` - project package: `settings/` (see above), `urls.py` (root
  URLconf), `celery.py` (Celery app, autodiscovers `tasks.py` per app), `wsgi.py`/`asgi.py`.
- `User/` - auth/profile app. `UserProfile` holds per-user risk preferences
  (`risk_tolerance`, `max_daily_loss_pct`, `max_position_size_pct`). Broker credentials are
  deliberately NOT here yet - they land once Phase 3's `BrokerAdapter` interface exists, and
  will be encrypted at rest rather than plain fields.
- `marketdata/` - PSX price data.
  - `models.py`: `Instrument` (symbol/exchange/sector), `PriceBar` (OHLCV, unique per
    instrument+timeframe+timestamp).
  - `providers/base.py`: `MarketDataProvider` interface (`get_history`, `get_latest`) +
    provider-agnostic `Bar`/`Quote` dataclasses - nothing outside `providers/psx.py` imports
    `psxdata` directly, so swapping data sources later doesn't touch callers.
  - `providers/psx.py`: `PSXProvider`, the only concrete implementation, wraps
    `psxdata.PSXClient`. Catches `psxdata.exceptions.PSXDataError` (the common base for all
    psxdata failures) and returns empty/`None` rather than raising, so one bad symbol/network
    blip doesn't blow up a batch sync.
  - `services.py`: `sync_instrument_history` / `sync_active_instruments` - upserts via
    `bulk_create(update_conflicts=True)`; used by both the management command and the Celery
    task so they share one code path.
  - `management/commands/sync_market_data.py`: `python manage.py sync_market_data [--symbol X]
    [--start YYYY-MM-DD] [--end YYYY-MM-DD]`.
  - `tasks.py`: `sync_all_active_instruments` Celery task - not yet wired to a beat schedule;
    add a `PeriodicTask` (django-celery-beat, via admin) for after PSX market close when this
    runs somewhere Celery is actually deployed.
- `strategies/` - pluggable signal generation.
  - `signals.py`: `Action` enum (buy/sell/hold) + `Signal` dataclass - the one shape every
    strategy produces.
  - `base.py`: `BaseStrategy` ABC - `generate_signals(bars: list[Bar]) -> list[Signal]`, one
    signal per bar (vectorized-per-history), so the same call replays in a backtest or (in
    Phase 3) just has its last element taken for a live decision.
  - `registry.py`: `@register_strategy("key")` + `get_strategy_class(key)`. The `Strategy`
    model stores this string key (not a Python import path) so admin-configured strategies
    can't reference arbitrary code.
  - `rules.py`: `MovingAverageCrossoverStrategy`, `RSIStrategy` - reference rule-based
    strategies, pandas-vectorized.
  - `manual.py`: `ManualSignalStrategy` - reads operator-entered `ManualSignal` rows for its
    configured `instrument_id`, same interface as any computed strategy.
  - `ml.py`: `MLModelStrategy` - wired to load a joblib-dumped model via `model_path` and
    call `.predict()`; **no training/feature pipeline exists yet** (not enough PriceBar
    history accumulated) - it degrades to HOLD until a real model is dropped in. Don't
    assume this produces meaningful signals.
  - `models.py`: `Strategy` (configured instance: name/key/params JSON/instruments
    M2M/is_active - `key` validity checked in `clean()`, not via field `choices`, to avoid a
    circular import with `manual.py`; see `apps.py`), `ManualSignal` (per-instrument/day
    operator entry).
  - `apps.py`: `ready()` imports `rules`/`manual`/`ml` so their `@register_strategy`
    decorators fire - the registry is only reliably populated after Django app startup, not
    at `models.py` import time.
  - `backtesting/engine.py`: `run_backtest(strategy, bars, initial_cash)` - long-only,
    single-instrument, all-in/all-out replay; returns `BacktestResult` with `cagr`,
    `max_drawdown`, `win_rate`, `sharpe`, `trades`, `equity_curve`. Position sizing/risk
    limits are deliberately NOT applied here - that's the `risk` app's job in Phase 3, against
    live trading, not this historical replay.
  - `management/commands/run_backtest.py`: `python manage.py run_backtest SYMBOL
    STRATEGY_KEY [--params '{"fast_period": 10}'] [--start] [--end] [--cash]`.
- `portfolio/` - `Account` (paper/live, cash_balance, `.equity` property = cash + mark-to-market
  positions) and `Position` (per account+instrument, unique together). `Account.broker` selects
  the `BrokerAdapter` (see `execution/brokers`) - only `"paper"` exists today.
- `risk/` - pre-trade checks, run before every order.
  - `checks.py`: `check_max_daily_loss` (against a `DailyEquitySnapshot` lazily captured the
    first time it's checked each day - not a separate scheduled job), `check_max_position_size`
    (SELL always passes - it only reduces exposure; existing position value counts toward the
    limit for BUY).
  - `engine.py`: `evaluate(account, instrument, side, quantity, price, strategy=None)` - reads
    thresholds from the account owner's `User.UserProfile` (falls back to that model's own
    defaults if no profile exists), runs both checks, and unconditionally writes a
    `RiskDecision` audit row (approved or not) before returning.
  - This app does NOT know about `execution.Order` - the duplicate-order guard lives in
    `execution/services.py` instead, specifically to avoid a risk<->execution circular import.
- `execution/` - orders and the trading cycle.
  - `models.py`: `Order` (full pending/submitted/filled/rejected/cancelled lifecycle, though
    `PaperBroker` resolves it synchronously in one call), `Trade` (a fill, separate from
    `Order` so partial fills from a future real broker aren't a schema change).
  - `brokers/base.py`: `BrokerAdapter` interface (`submit_order`, `cancel_order`,
    `get_positions`, `get_account`). `brokers/paper.py`: `PaperBroker`, the only
    implementation - fills against the latest stored `PriceBar` (not a live network call),
    updates `Position`/`Account` atomically, rejects on no price data / insufficient
    funds/position. `brokers/__init__.get_broker(account)` dispatches on `Account.broker`.
  - `services.place_order(account, instrument, side, quantity, strategy=None)` - the only path
    to create an Order: duplicate-order guard (same account+instrument+side within 5 minutes)
    -> `risk.engine.evaluate` -> `get_broker(account).submit_order`. Always call this, never
    construct `Order` + a broker directly.
  - `tasks.run_trading_cycle` - Celery task: for each active `Strategy` with an `account` set,
    builds it, generates a signal per configured instrument from stored `PriceBar` history, and
    calls `place_order` for the last non-HOLD signal. Order sizing is a fixed lot
    (`Strategy.params["order_quantity"]`, default 100) for BUY and "sell the whole position"
    for SELL - real position sizing is out of scope for v1; `risk.engine`'s max-position-size
    check is what actually bounds exposure. One strategy/instrument raising doesn't abort the
    rest of the cycle. Not yet wired to a beat schedule - same caveat as
    `marketdata.tasks.sync_all_active_instruments`.
  - `Strategy.account` (added in `strategies/migrations/0002_strategy_account.py`) is what
    `run_trading_cycle` uses to pick an account per strategy - a `Strategy` without one is
    never executed live, only backtested.
  - `notifications.send_alert(subject, message)` - fills/rejections call this (see
    `services._notify`). Emails `settings.ADMINS` (set via `ADMIN_EMAILS` env, comma-separated)
    and/or POSTs `{"text": ...}` to `settings.ALERT_WEBHOOK_URL` (a Slack/Telegram incoming
    webhook) if configured; with neither set, it only logs. Every failure inside is caught -
    an alerting problem must never break order placement.
- `api/` - DRF read API + the strategy on/off toggle. Routed at `/api/` (see
  `AutomaticStockTrading/urls.py`); `/api-auth/` adds session login for the browsable API in
  dev. All endpoints require authentication (`IsAuthenticated`); every viewset except
  `InstrumentViewSet`/`PriceBarViewSet` (reference data) uses `OwnerScopedMixin` to filter to
  the requesting user's own `Account`(s) via `owner_lookup` - staff users see everything.
  `StrategyViewSet` is the only writable one, and only `is_active` is writable (GET/PATCH
  only - no create/delete). `PositionSerializer` computes `market_value`/`unrealized_pnl` on
  the fly (not stored). There's no separate frontend - Django admin is the operational
  dashboard, per `docs/PLAN.md`.
  - Phase 7 read endpoints (E1) expose the research/forecasting data, all
    operator-global (no `OwnerScopedMixin`, plain `IsAuthenticated` reads):
    `news`/`research-snapshots`/`predictions` (`modeling.ModelPrediction`) and
    `backtests`/`backtest-runs` (`backtesting` models) are list/retrieve only;
    `trading-models` (`modeling.TradingModel`) is GET/PATCH with only `is_active`
    writable, mirroring `StrategyViewSet`. `news`/`research-snapshots`/`predictions`
    take `?symbol=` (shared `SymbolFilterMixin`, `symbol_lookup` ORM path).

When adding an app, register it in `AutomaticStockTrading/settings/base.py`
(`INSTALLED_APPS`) and wire its URLs into `AutomaticStockTrading/urls.py` via `include()`.

## `research` app (Phase 7, point-in-time feature providers)

Supplies the technical / news / fundamental / social features that
`forecasting` and `modeling` consume. Everything is as-of-timestamped: a
provider MUST NOT read a bar, headline, post, or report dated after its
`as_of`, and MUST return a bundle (possibly empty) rather than raise.

- `providers/base.py`: `FeatureProvider` ABC (`get_features(symbol, as_of,
  *, exchange) -> FeatureBundle`) + `FeatureBundle` dataclass (flat
  `features` float map + human-readable `sources` citations; `.merge()`
  refuses key collisions and cross-instrument merges) + a
  `@register_feature_provider("key")` registry mirroring
  `strategies/registry.py`.
- `providers/technical.py` (indicator library: SMA/EMA/RSI/MACD/Bollinger/
  ATR/stochastic, tested against hand-computed fixtures),
  `providers/news.py` (feedparser RSS ingest -> `NewsItem`; VADER sentiment
  on headlines; `news_features()` count/mean/last/trend windows),
  `providers/fundamentals.py` (`CompanyFundamental`, CSV/manual load),
  `providers/social.py` (`SocialMention`, fixture loader - live ingestion
  deferred).
- `models.py`: `NewsItem` (dedup on `url_hash`, nullable `sentiment`),
  `CompanyFundamental` (`ratios` JSON, `as_of_report_date`), `SocialMention`,
  `ResearchSnapshot` (upserted `features`/`sources`/`provider_keys` for one
  `symbol`+`as_of`).
- `services.py`: `build_feature_bundle()` merges every requested provider (a
  raising provider is logged and skipped); `get_or_build_snapshot()` upserts
  a `ResearchSnapshot`.
- `apps.py` `ready()` imports the provider modules so their decorators fire
  (same pattern as `strategies`).
- `management/commands/sync_research.py` (`--symbol`, `--as-of`);
  `tasks.py` `ingest_news` / `sync_all_research` (unscheduled).
- Leak test: a headline published after `as_of` is excluded from the bundle.

## `forecasting` app (Phase 7, leakage-strict next-day forecasting)

The strict next-day-close path (kept deliberately separate from the
UI-driven `modeling` studio). `research` supplies technical/news/fundamental/
social features. The
`forecasting` app registers `naive`, `drift`, `sarima`, `ets`, `ridge`,
`elasticnet` and `gradient_boosting` predictors through
`apps.ready()` (plus `lstm` when the optional `torch` extra is installed). `TrainingFrame` separates future labels and label-availability
timestamps from `PredictionFrame` inputs. `assemble_training_frame` retains
warmup history but only labels observable by its aware `end` timestamp.
Daily bars and date-only fundamental releases become usable at the next local
midnight; this is conservative until precise availability timestamps exist.
`predict_next` requires an explicit target session date, without guessing
holidays or consulting future bars. Drift rejects inference before its latest
training label was available. Walk-forward evaluation lives in
`forecasting/backtesting/` (library + `backtest_predictor` command); a run can
be frozen as a `forecasting.ForecastBacktestRun` row via
`forecasting.services.run_forecast_backtest` (or `backtest_predictor --save`) -
one flat, JSON-safe, never-raises record of config + folds + pooled
predicted-vs-actual + metrics + trading translation + `looks_leaky`. No
per-forecast prediction persistence, fitted artifacts or training command on
this strict path yet (those live in the parallel `modeling` app).

Usage and limitations: `docs/FORECASTING.md`. Keep `docs/TASKS.md` updated;
B6 adds `sarima`/`ets` statistical predictors with training-only parameter fits and prefix replay.
B7 (`forecasting/linear.py`) adds `ridge`/`elasticnet` over the full point-in-time feature frame:
next-return target rebuilt to a close, imputer+scaler fit inside an sklearn `Pipeline`, feature
schema pinned at fit, row-independent prediction (no prefix replay). B8 (`forecasting/trees.py`)
adds `gradient_boosting` (`HistGradientBoostingRegressor`) over the same frame; B7 and B8 share
`forecasting/_frame_model.py::FrameModelPredictor` (the tree path skips the imputer/scaler stage
since HGB handles NaNs natively). B9 (`forecasting/deep.py`) adds the optional `lstm` predictor -
another `FrameModelPredictor` subclass (median imputer -> sklearn-wrapped `nn.LSTM` over the last
`lookback` rows); `torch` is soft-imported from `requirements-ml.txt` and nothing registers when
it is absent. C-phase walk-forward over the `forecasting` predictors is done
(`forecasting/backtesting/` + `ForecastBacktestRun` persistence).

- `models.py`: just `ForecastBacktestRun` - one flat, JSON-safe,
  never-raises row (config + folds + pooled predicted-vs-actual + metrics +
  trading translation + `looks_leaky`). No per-forecast persistence or
  fitted-artifact storage on this path.
- `registry.py`: `@register_predictor` / `get_predictor_class` /
  `registered_keys`; `services.py`: `run_forecast_backtest()` and
  `latest_forecast(symbol, key)` (the latter powers the `marketdata`
  symbol-detail live-forecast panel).
- UI at `/forecast-backtests/` (`forecasting/urls.py` + `views.py` FBVs +
  `templates/forecasting/`): a config form -> walk-forward run -> per-fold
  table, skill badge, predicted-vs-actual and equity SVG polylines (D7
  strict-path runner). Extends `marketdata/base.html`.

See `docs/FORECASTING.md`.

## `modeling` app (Phase 7, configurable-model studio)

Separate from `forecasting` (which stays the leakage-strict next-day-close
path). `modeling` is the UI-driven studio: a `TradingModel` row is an
estimator key + `feature_spec` (JSON list) + `target_spec` (JSON dict) +
instruments + train window; it trains to a joblib artifact under
`settings.MODEL_ARTIFACT_DIR` (default `<repo>/artifacts/models/`,
gitignored) and predicts into persisted `ModelPrediction` rows with
actual-value backfill.

- `estimators.py`/`deep.py`: `@register_estimator` registry (mirrors
  `strategies/registry.py`), populated in `apps.ready()`. sklearn linear /
  trees / `mlp` + trivial baselines (`naive_last`/`drift`/`seasonal_naive`,
  which read an `ohlc` close-lag column); `lstm` needs the optional
  `requirements-ml.txt` torch extra and is otherwise "unavailable".
- `features.py`: point-in-time feature builder - `ohlc`/`return`/`technical`
  (from `research`)/`research`/`strategy_signal` (a `strategies` `Strategy`
  or key, mapped to {-1,0,1})/`manual_signal`/`calendar`. `validate_spec`
  is Django-import-free so `TradingModel.clean()` stays cheap.
- `targets.py`: `horizon_close`/`horizon_return`/`direction`/
  `weekday_anchored` (Mon->Fri same week)/`multistep`. "Next local
  midnight" label availability, same as `forecasting`. `predict` needs an
  explicit `target_date` except for `weekday_anchored`.
- `dataset.py`: pooled X/y across the model's instruments; trailing
  time-ordered holdout (single split - **not** walk-forward); a row is kept
  only if its label was observable by `train_end`.
- `training.py` (`train_model`) never raises - records a `ModelTrainingRun`.
  `prediction.py` (`predict`, `backfill_actuals`). `services.py` is the thin
  wrapper used by views/commands/tasks.
- Commands: `train_model`, `predict_model`, `backfill_actuals`. Tasks
  (`tasks.py`, unscheduled): `train_model_task`, `run_model_predictions`,
  `backfill_prediction_actuals`.
- UI under `/modeling/` (FBVs, extends `marketdata/base.html`). Adds
  `scikit-learn` to `requirements.txt`.

Usage and the full feature/target reference: `docs/MODELING.md`.

## `backtesting` app (Phase 7, walk-forward evaluation)

Walk-forward backtesting of a `modeling.TradingModel` - the repeated-retrain-
through-time view the `modeling` app's single trailing holdout can't give,
plus a forecast -> trade -> equity-curve translation. Routed at `/backtests/`
(NOT `/backtesting/`, which is the in-progress `strategies` UI). Adds no new
dependencies.

- `models.py`: `Backtest` (config: which model, `fit_mode`
  `walk_forward`/`frozen_artifact`, optional `training_run` FK (pins an
  artifact for `frozen_artifact`), `scheme` `expanding`/`rolling`,
  `train_span`/`test_span`/`step`/`gap` in *sessions with data*,
  `long_threshold`/`allow_short` position rule, cost bps, cash;
  `clean()` accepts every `modeling` target type (`weekday_anchored` is scored
  like `horizon_close` at a weekly decision cadence; `multistep` is collapsed
  to its final horizon by `engine._final_step` in both scorers) and keeps
  `SUPPORTED_TARGETS` only as an opt-in gate for future target types; requires
  a trained artifact when `fit_mode` is `frozen_artifact`; `.artifact_path`
  resolves the pinned run's path or the model's latest), `BacktestRun` (execution row, mirrors
  `modeling.ModelTrainingRun` - never-raises, records `status`/`error`),
  `BacktestFold`, `BacktestPrediction` (pooled OOS predicted-vs-actual),
  `BacktestTrade`.
- `walkforward.py`: pure `generate_folds()` - marches `(train, test)` windows
  forward, asserts `train_end < test_start` with a `gap` embargo every fold.
- `engine.py` (`run_backtest`): reuses `modeling.dataset.build_dataset`
  (point-in-time X/y/anchor/available_at), `modeling.metrics.*` (accuracy) and
  `strategies.backtesting.engine.BacktestResult` (CAGR/drawdown/Sharpe/win
  rate). `_execute` picks a scorer by `fit_mode`: `_score_walk_forward` fits a
  fresh `modeling.training.build_pipeline` per fold and drops any training row
  whose label wasn't observable before that fold's first test decision;
  `_score_frozen` `joblib.load`s the model's stored artifact, checks
  `feature_names`/`target_spec` still match, and scores every row dated
  strictly after the artifact's training cut-off (`min(trained_at, train_end)`,
  both recorded in the artifact by `modeling.training`; pre-existing artifacts
  fall back to the live `TradingModel.train_end`) as one pseudo-fold - and
  builds that scoring dataset out to today, not capped at `model.train_end`, so
  a model trained on a past window still has sessions left to score. Both feed
  the same forecast->position->equity tail. Persists everything; failures land
  on the run.
- `metrics.py`: `positions_from_forecast` + per-instrument
  `simulate_instrument` (all-in/all-out, cost on every position change) +
  `combine_equity_curves` (equal cash split, forward-filled union).
- `services.py` (deferred-import wrapper), `tasks.py` (`run_backtest_task`,
  `run_active_backtests` - unscheduled),
  `management/commands/backtest_model.py` (`--fit-mode` / `--training-run`
  plus the window flags override stored config for one run), `admin.py`
  (all 5 models), UI under `/backtests/` (FBVs extending
  `marketdata/base.html`).

Usage, leakage guarantees and v1 limitations: `docs/BACKTESTING.md`. This
covers the intent of `docs/TASKS.md` Phase C for the `modeling` studio path.

## Dashboard - "PSX Observatory" (Phase 7, Phase D)

The Phase D operator dashboard was built as **plain server-rendered Django
pages, not a separate `dashboard` app** and not an SPA - there is no
`dashboard` in `INSTALLED_APPS`, no django-htmx, no build step. Charts are
hand-rolled inline SVG polylines; styling is one static stylesheet
(`marketdata/static/marketdata/dashboard.css`). Django admin remains the
fallback for anything without a bespoke page.

- Shell: `marketdata/templates/marketdata/base.html` - the `PSX Observatory`
  header + top nav shared by every Phase 7 UI. Each app's templates
  `{% extends "marketdata/base.html" %}`. `marketdata:login`/`logout` are the
  auth entry points; all dashboard views are `login_required`.
- `marketdata/views.py` owns the core pages: `dashboard` (market overview),
  `instruments` (searchable table with last close + last persisted
  `modeling.ModelPrediction` vs actual), `instrument_detail` (candlestick +
  volume, SMA/EMA overlays, a live-forecast panel via
  `forecasting.services.latest_forecast` with a `?predictor=` selector, and
  news/social/fundamentals panels read straight from `research` tables, each
  degrading independently).
- The other panels live in their own apps' UIs, all linked from the shared
  nav: `/modeling/` (studio), `/modeling/leaderboard/` (D8 accuracy
  leaderboard - `modeling/leaderboard.py`, ranks active `TradingModel`s by
  trailing out-of-sample accuracy/skill; a bad row logs and is skipped, never
  500s), `/backtests/` (walk-forward runner), `/forecast-backtests/`
  (strict-path runner), `/backtesting/` (`strategies` UI), plus `/admin/` and
  `/api/`.

## Deployment

See `docs/DEPLOYMENT.md` for the full picture (two scheduling shapes, open cloud-provider
choice, secrets handling). Short version: `Dockerfile` is a multi-stage build ending in
`gunicorn`; `docker-compose.yml` mirrors the full stack locally (web/worker/beat/postgres/
redis). Both scheduled jobs (`sync_market_data`, `run_trading_cycle`) are also plain
management commands that run the same code with no Celery broker/worker involved -
`python manage.py run_trading_cycle` - meant to be invoked directly by a cloud managed
scheduler (EventBridge/Cloud Scheduler) as a one-off container task, which is the
plan's preferred shape over running a persistent Celery beat process.
