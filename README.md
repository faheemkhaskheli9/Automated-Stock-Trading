# Automated-Stock-Trading

An automated trading system for the Pakistan Stock Exchange (PSX): a pluggable
strategy framework (rule-based, manual-entry, ML-driven), a paper broker and
risk engine, a leakage-strict forecasting/modeling stack with walk-forward
backtesting, a weekly signal-delivery feed, and a server-rendered operator
dashboard ("PSX Observatory"). Paper trading first — live trading is a later,
separately-gated phase (PSX has no self-serve broker API today).

See [`docs/PLAN.md`](docs/PLAN.md) for the full build-out plan and rationale,
and [`CLAUDE.md`](CLAUDE.md) for the detailed per-app architecture reference.

## Status

| Phase | Scope | State |
|---|---|---|
| 0 | Project hygiene (settings, env config, CI, linting) | done |
| 1 | `marketdata` — PSX data pipeline | done |
| 2 | `strategies` — pluggable strategy framework + backtesting | done |
| 3 | `portfolio` / `risk` / `execution` — paper broker + trading cycle | done |
| 4 | `api` (DRF) + alerting | done |
| 5 | Docker / deployment docs | done (not build-verified in this env) |
| 6 | Live trading | not started — gated on a real PSX broker/vendor relationship |
| 7 | Research/forecasting foundation, modeling studio, model search, walk-forward backtesting, "PSX Observatory" dashboard | in progress |
| 8 | `signalfeed` — weekly Mon→Fri signal delivery | in progress |
| 9 | Operator UI — routine actions moved off admin into "PSX Observatory" | done |

Task-by-task tracking for Phase 7 lives on GitHub Projects board #5, not in a
markdown file.

## What's in here

- **Market data** — PSX OHLCV bars via the `psxdata` scraper library (no
  official free PSX API exists), stored per-instrument/timeframe.
- **Strategies** — one `BaseStrategy` interface behind rule-based
  (moving-average crossover, RSI), manual-entry, and ML-driven signal
  sources, plus a single-instrument backtesting engine.
- **Paper trading** — `Account`/`Position`, a `BrokerAdapter` interface with
  a simulated `PaperBroker`, and pre-trade risk checks (max daily loss, max
  position size) that write an audit trail before every order.
- **Research & forecasting (Phase 7)** — point-in-time technical/news/
  fundamental/social feature providers; a leakage-strict next-day-close
  `forecasting` path (naive/drift/sarima/ets/ridge/elasticnet/gradient
  boosting/lstm); a configurable `modeling` studio (estimators, feature
  specs, target specs, ensembles) with persisted predictions; a
  `modelsearch` app to sweep estimators × hyper-parameter grids; a
  `backtesting` app for walk-forward evaluation of a trained model.
- **Weekly signals (Phase 8)** — `signalfeed` turns a trained model into a
  plain-language weekly call ("Mon → Fri: ENGRO UP +2.3%"), gated on live
  out-of-sample accuracy, with advisory position sizing and email/webhook/
  Telegram delivery. Advisory only — it never places an order.
- **PSX Observatory** — a server-rendered operator dashboard (plain Django
  views + inline SVG charts, no SPA/build step) covering market data,
  strategies, portfolio, risk, execution, research, modeling, model search,
  backtesting, and the signal feed. Django admin remains the power-user
  fallback for anything without a bespoke page.
- **API** — a DRF read API (plus the strategy/model on-off toggle) at `/api/`,
  scoped to each user's own accounts.

## Running locally

```powershell
py -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
cp .env.example .env   # adjust values; defaults work for local sqlite dev

.venv/Scripts/python.exe manage.py migrate
.venv/Scripts/python.exe manage.py createsuperuser
.venv/Scripts/python.exe manage.py runserver
```

Open http://127.0.0.1:8000 and sign in — this lands on the PSX Observatory
dashboard. From there:

- **Market data**: pull a symbol's history (`marketdata.add_pricebar`
  permission, staff included) or use `python manage.py sync_market_data
  --symbol OGDC` for a larger backfill.
- **Strategies**: configure a strategy under `/backtesting/strategies/`, or
  run a one-off historical replay with `python manage.py run_backtest SYMBOL
  STRATEGY_KEY`.
- **Portfolio / trading**: create a paper `Account` under `/portfolio/`,
  then place paper orders under `/trading/`.
- **Research / modeling / model search / backtests**: build feature
  snapshots at `/research/`, train a model at `/modeling/`, sweep
  hyperparameters at `/model-search/`, and walk-forward evaluate at
  `/backtests/`.
- **Signals**: configure a watchlist at `/signals/watchlist/` and generate/
  send/recap weekly calls from `/signals/`.

`TIME_ZONE` is `Asia/Karachi` (PSX market hours), which matters for
scheduling. See [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) for Docker
Compose, the cloud-managed-scheduler shape, and `AutomaticStockTrading/
schedules.py` (the single source of truth for recurring jobs).

## Development

```powershell
pytest                       # or: python manage.py test
black . ; isort . ; ruff check .
```

CI (`.github/workflows/ci.yml`) runs the same formatting/lint/test suite on
every push and PR. See [`CLAUDE.md`](CLAUDE.md) for the full app-by-app
architecture reference, and [`docs/`](docs/) for per-feature design docs
(`FORECASTING.md`, `MODELING.md`, `MODEL_SEARCH.md`, `BACKTESTING.md`,
`SIGNALS_PLAN.md`, `DEPLOYMENT.md`, `IMPROVEMENT_BACKLOG.md`).
