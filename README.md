# Automated-Stock-Trading

An automated trading system for the Pakistan Stock Exchange (PSX) — pluggable
strategies (rule-based, manual, ML-driven), paper trading first, live trading later.

See [`docs/PLAN.md`](docs/PLAN.md) for the full build-out plan and
[`CLAUDE.md`](CLAUDE.md) for setup/commands.

## PSX data viewer

The home page provides a signed-in dashboard for saved PSX daily prices, a closing-price
chart, date filters, paginated OHLCV history, and CSV export. Users with the
`marketdata.add_pricebar` permission (including superusers) can fetch and save a symbol.
Fetching without dates imports the past year; repeat imports update existing dates.
Saved history remains available when the provider is unavailable. Chart and table use
stored daily bars, not live quotes. The chart displays up to 365 sessions; CSV includes
the entire selected range. Imports run within the web request, so use the existing
`sync_market_data` command for large backfills.

Run locally on Windows after installing the project dependencies:

```powershell
.venv/Scripts/python.exe manage.py migrate
.venv/Scripts/python.exe manage.py createsuperuser
.venv/Scripts/python.exe manage.py runserver
```

Open http://127.0.0.1:8000 and sign in. Enter a symbol (for example, OGDC), then
choose **Fetch & save**. Use **View saved** to query the database without a network fetch.
Data persists in `db.sqlite3` by default, or the database configured by `DATABASE_URL`.
Back up that database to retain collected history. The existing command and Celery task
also populate the same database for use by the viewer and future analysis.
