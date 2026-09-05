# Automated Stock Trading — Build-Out Plan

## Context

The repo currently contains only a freshly generated Django 6.0 skeleton:
`django-admin startproject AutomaticStockTrading` + `startapp User`, with the
`User` app's models/views/admin/tests all still empty stubs. Nothing beyond
`.gitignore` and a one-line README is even committed to git yet. There is no
requirements file, no market-data integration, no strategy or order logic,
no broker connection, and no deployment setup.

Decisions confirmed with the user:
- **Market**: Pakistan Stock Exchange (PSX)
- **Strategy approach**: support all of rule-based, ML-driven, and
  manual-signal strategies through one pluggable framework — not just one
- **Execution mode**: paper trading first, live trading later
- **Deployment**: containerized, cloud-managed (managed scheduler instead of
  hand-rolled cron)

This plan turns the empty skeleton into a working, extensible automated
trading system in incremental, independently-shippable phases.

### PSX integration reality check (from research)
- **Market data**: no official free API; the open-source `psxdata`
  (https://github.com/mtauha/psxdata) and `psx-data-reader` libraries scrape
  the public PSX site for EOD/historical data with no key required — good
  enough for backtesting and a v1 data pipeline. PSX also sells an official
  paid data-vending feed for production-grade needs later.
- **Order execution**: PSX has no public self-serve broker API. The only
  programmatic order-routing option found is a third-party vendor
  (StockIntel) that bridges to SECP-licensed brokers — this requires a
  business/vendor relationship and broker account, not just code. Because of
  this, the plan builds a `BrokerAdapter` interface with a **paper/simulated
  broker as the only concrete implementation for now**, so the rest of the
  system (risk, orders, portfolio, dashboard) is fully built and testable
  without waiting on that external dependency. A real PSX adapter becomes a
  drop-in later.

---

## Phase 0 — Project hygiene (foundation)

1. Commit the existing skeleton as-is (it isn't tracked yet), then layer in:
   - `requirements.txt` / `pyproject.toml` pinning Django, `django-environ`,
     `celery`, `redis`, `djangorestframework`, `psycopg[binary]`,
     `pandas`, `psxdata`.
   - Split settings: `AutomaticStockTrading/settings/{base,dev,prod}.py`,
     load `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`, DB and Redis URLs from
     environment via `django-environ` + a `.env.example`. Rotate the
     currently-hardcoded `SECRET_KEY` out of source.
   - Switch `DATABASES` from sqlite to Postgres (via env var), matching what
     will run in containers/cloud.
   - Add `.pre-commit-config.yaml` (black, ruff/flake8, isort).
   - Add `pytest.ini` / `pytest-django` config and a GitHub Actions CI
     workflow (lint + test) under `.github/workflows/ci.yml`.
2. Rename/clarify the `User` app's role: keep it for auth/profile concerns
   (broker credential storage, risk preferences per user) rather than
   leaving it empty.

## Phase 1 — Market data pipeline

New app `marketdata`:
- Models: `Instrument` (symbol, sector, exchange), `PriceBar` (OHLCV,
  timeframe, timestamp, instrument FK).
- `marketdata/providers/psx.py`: thin wrapper around `psxdata` to fetch
  EOD history + latest quotes, isolated behind a small provider interface
  (`get_history(symbol, start, end)`, `get_latest(symbol)`) so the data
  source can be swapped (e.g. for the paid PSX feed) without touching
  callers.
- Management command / Celery task to backfill and then incrementally
  update `PriceBar` data, scheduled for after PSX market close
  (Asia/Karachi timezone).

## Phase 2 — Strategy framework (pluggable, per user's requirement)

New app `strategies`:
- `strategies/base.py`: `BaseStrategy` ABC with `generate_signals(price_history) -> list[Signal]`
  and metadata (name, params schema, timeframe).
- Three concrete signal sources built on the same interface:
  - **Rule-based**: `MovingAverageCrossoverStrategy`, `RSIStrategy` as
    reference implementations using `pandas`/`ta`-style indicators.
  - **Manual**: `ManualSignalStrategy` that reads operator-entered signals
    (via Django admin/API) instead of computing them — same interface,
    same downstream risk/order pipeline.
  - **ML-driven**: `MLModelStrategy` stub that loads a serialized model
    (path/version configurable) and calls `.predict()` on engineered
    features — the training/feature pipeline itself is scoped as later
    work once enough historical data has accumulated; v1 just wires the
    interface so it's a drop-in.
- `Strategy` model to persist configured instances (which class, params,
  enabled instruments, active/inactive) so strategies are managed data, not
  hardcoded code paths.
- `backtesting/` module: replay `PriceBar` history through any
  `BaseStrategy`, simulate fills, and report metrics (CAGR, max drawdown,
  win rate, Sharpe) — this is what validates a strategy before it's ever
  allowed to run live.

## Phase 3 — Orders, portfolio, risk, and the paper broker

New apps `orders` (or `execution`) and `portfolio`:
- Models: `Account` (paper or live, starting balance), `Order` (status
  state machine: pending → submitted → filled/rejected/cancelled),
  `Trade` (execution fills), `Position` (per-instrument holdings/PnL).
- `execution/brokers/base.py`: `BrokerAdapter` interface
  (`submit_order`, `cancel_order`, `get_positions`, `get_account`).
- `execution/brokers/paper.py`: the only concrete adapter for now —
  simulates fills against `marketdata` prices, updates `Position`/`Account`
  in the same DB. This is what "paper trading first" runs on end-to-end.
- `risk/` module: pre-trade checks run between signal and order —
  max position size, max daily loss, per-instrument exposure cap, duplicate
  order guard. Every rejected/approved decision is logged with its reason.
- Celery beat task `run_trading_cycle`: during PSX market hours, for each
  active `Strategy` → generate signals → risk-check → submit to the
  account's configured `BrokerAdapter`. Every step writes an audit log
  entry (strategy, inputs, decision, timestamp) for traceability.

## Phase 4 — API & dashboard

- Add `djangorestframework`; expose read endpoints for positions, orders,
  trades, PnL, and strategy on/off toggles; reuse Django admin as the
  first operational UI (fast to get, fine for a single-operator system)
  before investing in a custom frontend.
- Add alerting hook (email or a webhook to Telegram/Slack) for order
  fills, rejected trades, and risk-limit breaches.

## Phase 5 — Containerization & cloud deployment

- `Dockerfile` (multi-stage: deps → app) + `docker-compose.yml` for local
  parity: `web`, `worker` (Celery), `beat`, `redis`, `postgres`.
- Cloud target: containers pushed via CI to a registry, run as services
  with a **managed scheduler** driving `run_trading_cycle` instead of a
  hand-rolled cron/beat box (e.g. AWS ECS Fargate + EventBridge Scheduler,
  or GCP Cloud Run Jobs + Cloud Scheduler — exact provider is an open
  choice to make when this phase starts, since none was specified).
- Managed Postgres + Redis (e.g. RDS/Cloud SQL + ElastiCache/Memorystore,
  or a simpler provider like Railway/Fly.io/Render if lower ops overhead
  is preferred).
- Secrets via the cloud provider's secret manager, not `.env` in the image.

## Phase 6 — Live trading (later, gated on an external vendor decision)

- Once paper trading has a track record from backtests + live paper runs,
  evaluate a real order-routing vendor (e.g. StockIntel's PSX API) or a
  direct broker relationship, and implement a second `BrokerAdapter` for
  it. This is intentionally last because it depends on signing up with a
  third party, not just code.

---

## Suggested execution order

Phase 0 → 1 → 2 (backtesting proves strategies work) → 3 (paper trading
loop live) → 4 (visibility) → 5 (deploy it) → 6 (real money, later).
Each phase is independently shippable and testable before moving on.

## Verification approach per phase

- Phase 0: `python manage.py check`, CI pipeline green on a trivial PR.
- Phase 1: management command pulls real PSX EOD data into `PriceBar` for
  a sample symbol; spot-check against psx.com.pk.
- Phase 2: backtest a reference strategy (e.g. MA crossover) over stored
  history and confirm metrics are computed and sane.
- Phase 3: run `run_trading_cycle` against the paper broker in a dev
  environment for a full simulated session; confirm orders/positions/PnL
  update correctly and risk checks block an intentionally-oversized order.
- Phase 4: hit the DRF endpoints / admin and confirm they reflect Phase 3
  state; trigger an alert and confirm delivery.
- Phase 5: `docker compose up` reproduces the full stack locally; a cloud
  deploy runs one full scheduled cycle end-to-end.

---

## Phase 7 — Next-day close forecasting (in progress)

Added after the request for a price-prediction "agent". Full design in
`docs/FORECASTING_PLAN.md`; live task list with status in `docs/TASKS.md`.

Summary: three new apps —
- `research` — pluggable `FeatureProvider` library (technical indicators
  working, RSS news + VADER sentiment working, fundamentals/social stubbed
  behind the interface), all **point-in-time correct**, cached as
  `ResearchSnapshot`.
- `forecasting` — `BasePredictor` framework + registry (mirrors
  `strategies/`), multiple user-selectable predictors (naive/drift
  baselines, SARIMA/ETS, Ridge/ElasticNet, gradient boosting, optional
  PyTorch LSTM), `PredictionModel`/`Prediction` models, and a **walk-forward
  backtester with enforced anti-leakage** (fresh model per fold, strict
  train/test time ordering, point-in-time features, leak-canary tests,
  skill-vs-naive scoring).
- `dashboard` — Django + HTMX + Tailwind + Plotly web UI: instruments,
  symbol detail (chart + indicators + forecast + news), predictor
  catalogue, backtest runner, accuracy leaderboard.

Market-agnostic by construction (keyed on `Instrument.exchange`); PSX is the
only wired provider, others drop in later.
