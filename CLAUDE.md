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

When adding an app, register it in `AutomaticStockTrading/settings/base.py`
(`INSTALLED_APPS`) and wire its URLs into `AutomaticStockTrading/urls.py` via `include()`.

## Forecasting foundation (Phase 7, B1-B5 complete)

`research` supplies technical/news/fundamental/social features. The new
`forecasting` app registers `naive` and `drift` predictors through
`apps.ready()`. `TrainingFrame` separates future labels and label-availability
timestamps from `PredictionFrame` inputs. `assemble_training_frame` retains
warmup history but only labels observable by its aware `end` timestamp.
Daily bars and date-only fundamental releases become usable at the next local
midnight; this is conservative until precise availability timestamps exist.
`predict_next` requires an explicit target session date, without guessing
holidays or consulting future bars. Drift rejects inference before its latest
training label was available. No forecast persistence, fitted artifacts,
training command or walk-forward evaluation is implemented yet.

Usage and limitations: `docs/FORECASTING.md`. Keep `docs/TASKS.md` updated;
B6 (statistical predictors) is next. Full suite: 133 tests passing after B1-B5.

## Deployment

See `docs/DEPLOYMENT.md` for the full picture (two scheduling shapes, open cloud-provider
choice, secrets handling). Short version: `Dockerfile` is a multi-stage build ending in
`gunicorn`; `docker-compose.yml` mirrors the full stack locally (web/worker/beat/postgres/
redis). Both scheduled jobs (`sync_market_data`, `run_trading_cycle`) are also plain
management commands that run the same code with no Celery broker/worker involved -
`python manage.py run_trading_cycle` - meant to be invoked directly by a cloud managed
scheduler (EventBridge/Cloud Scheduler) as a one-off container task, which is the
plan's preferred shape over running a persistent Celery beat process.
