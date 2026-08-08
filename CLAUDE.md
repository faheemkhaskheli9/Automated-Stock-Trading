# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

Automated Stock Trading system targeting the Pakistan Stock Exchange (PSX). Being built in
phases per `docs/PLAN.md` (the full approved plan, with rationale):

- **Phase 0 (done)**: project hygiene - settings split, env config, requirements, CI, linting.
- **Phase 1 (done)**: `marketdata` app - PSX data pipeline (see below).
- **Phase 2+ (not yet built)**: pluggable strategy framework + backtesting,
  orders/portfolio/risk + paper broker, API/dashboard, containerized deploy, live trading
  (gated on a real PSX broker/vendor relationship - see below).

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
- Future apps (per the plan, not yet created): `strategies` (+ `backtesting`),
  `execution`/`orders`, `portfolio`, `risk`.

When adding an app, register it in `AutomaticStockTrading/settings/base.py`
(`INSTALLED_APPS`) and wire its URLs into `AutomaticStockTrading/urls.py` via `include()`.
