# Deployment

Phase 5 of `docs/PLAN.md`: containerized, cloud-managed, with a managed
scheduler doing the job a hand-rolled cron box would otherwise do. This
doc covers what's built and the open choices left for whoever deploys it.

## What's here

- **`Dockerfile`** - multi-stage build. Builder stage installs
  `requirements.txt` into an isolated prefix; final stage is a slim runtime
  image, runs as a non-root user, serves static files via WhiteNoise
  (`collectstatic` runs at build time), and starts `gunicorn`.
- **`docker-compose.yml`** - local parity for the full stack: `web`,
  `worker` (Celery), `beat` (Celery beat), `postgres`, `redis`. This is for
  local testing, not a production manifest - see below for how the cloud
  target differs.
- **`.github/workflows/ci.yml`** - a `docker-build` job builds the image
  (doesn't push - no registry is configured yet) on every push/PR, so a
  broken Dockerfile fails CI.

## Dependencies (Phase 7)

`requirements.txt` now also carries the Phase 7 research/forecasting/modeling
stack: `scikit-learn` (every `modeling` estimator and every `forecasting`
linear/tree predictor), `statsmodels` (the `sarima`/`ets` predictors),
`feedparser` + `vaderSentiment` (soft-imported by `research/providers/news.py`
for live RSS ingestion only). `pandas`/`numpy`/`scipy`/`joblib` come in with
those. The Dockerfile installs `requirements.txt` unchanged, so the default
image already has all of this.

- **`requirements-ml.txt`** (`-r requirements.txt` + `torch`) is an **optional
  extra**, not installed by the Dockerfile. The only things that need it are
  the `lstm` estimator (`modeling/deep.py`) and the `lstm` predictor
  (`forecasting/deep.py`); both soft-import `torch` and skip their own
  registration when it is absent, so the apps, migrations and the whole test
  suite run fine without it. Build a torch-enabled image only where you
  actually want LSTM models available - it adds substantial image size and
  build time. To do so, change the builder stage's install line to
  `-r requirements-ml.txt` (or add a second `pip install`), or maintain a
  separate `Dockerfile.ml`.
- `pandas-ta` / `django-htmx` / `plotly` were on the original Phase 7 plan but
  are **not** dependencies: the technical indicators are hand-rolled in
  `research/providers/technical.py` and the dashboard is server-rendered with
  inline SVG (no htmx, no Plotly).

## Two ways to run the scheduled jobs

There are two scheduled jobs: `marketdata.tasks.sync_all_active_instruments`
(after PSX market close) and `execution.tasks.run_trading_cycle` (during
market hours). Both exist as Celery tasks *and* as plain management
commands that call the same code directly, in-process, with no Celery
broker/worker involved:

```
python manage.py sync_market_data
python manage.py run_trading_cycle
```

This means there are two legitimate deployment shapes:

1. **Persistent Celery** (what `docker-compose.yml` mirrors): run `web`,
   `worker`, and `beat` as long-lived services; schedule via
   `django_celery_beat`'s `PeriodicTask` rows (manageable from the admin).
   Simple, but `beat` is one more long-running process to keep alive - the
   "hand-rolled cron/beat box" the plan explicitly wanted to avoid.

2. **Managed scheduler + one-off tasks** (the plan's preferred shape): run
   only `web` as a persistent service. Point a managed scheduler directly
   at the management commands above, as one-off container invocations, and
   drop `worker`/`beat` entirely:
   - **AWS**: EventBridge Scheduler → ECS `RunTask` (Fargate), container
     command overridden to `python manage.py run_trading_cycle` /
     `sync_market_data`.
   - **GCP**: Cloud Scheduler → Cloud Run Jobs execution, same command
     override.

Option 2 is recommended - it's what "managed scheduler instead of a
hand-rolled cron/beat box" means in practice here, and it's one fewer
always-on process to operate. Option 1 remains available (and is what
`docker-compose.yml` runs locally) since Celery is still wired up for
future work that genuinely needs a queue/worker (e.g. retrying a failed
broker call asynchronously) rather than a scheduled one-shot.

## Phase 7 background jobs

Phase 7 adds more work that wants to run on a schedule. Like the two jobs
above, every one exists both as a `@shared_task` and as a plain management
command running the same code in-process, so both deployment shapes apply
(managed scheduler → one-off container command is still preferred):

| Command | Task | Cadence | Purpose |
|---|---|---|---|
| `python manage.py sync_research [--symbol X] [--as-of ...]` | `research.tasks.sync_all_research` | daily, after `sync_market_data` | rebuild the point-in-time feature/news bundle per instrument |
| `python manage.py predict_model` *(per model)* | `modeling.tasks.run_model_predictions` | daily, after `sync_research` | write next-session `ModelPrediction` rows for every active `TradingModel` |
| `python manage.py backfill_actuals` | `modeling.tasks.backfill_prediction_actuals` | daily | fill realised closes onto past predictions once their session closes |
| `python manage.py train_model <id>` | `modeling.tasks.train_model_task` | ad hoc / periodic retrain | (re)fit a `TradingModel` to a joblib artifact |
| `python manage.py backtest_model <id>` | `backtesting.tasks.run_backtest_task` / `run_active_backtests` | ad hoc | walk-forward evaluate a `TradingModel` |

None are wired to a beat schedule in the repo - add `PeriodicTask` rows
(Option 1) or managed-scheduler triggers (Option 2) when this is deployed.
Ordering matters: `sync_market_data` → `sync_research` → `run_model_predictions`
→ `backfill_prediction_actuals`. `TIME_ZONE` is `Asia/Karachi`, so "after PSX
close" is roughly 15:30 PKT.

## Model-artifact storage

`modeling` writes trained models as joblib files under `MODEL_ARTIFACT_DIR`
(`.env` / env var; default `<repo>/artifacts/models/`, gitignored) and
`predict` / `backtest --fit-mode frozen_artifact` read them back. In the
managed-scheduler shape the `train` run and the later `predict` run are
**separate ephemeral containers**, so this directory must be a **persistent,
shared, writable volume**, not container-local disk:

- **AWS**: an EFS access point mounted at `MODEL_ARTIFACT_DIR` on both the
  `web` service and the scheduled `RunTask`s.
- **GCP**: a Filestore share (or a GCS bucket via `gcsfuse`) mounted the same
  way on Cloud Run.
- **Persistent Celery shape**: a named Docker/host volume shared by `web` and
  `worker` (`docker-compose.yml` currently runs them from the same image and
  working tree, so local dev already shares `<repo>/artifacts/`).

If the volume is lost, models simply need retraining - no data-loss risk, but
`predict` degrades (it needs a current artifact) until `train_model` runs
again.

## Open choices (not decided by this repo)

- **Cloud provider**: AWS vs GCP vs something simpler (Railway/Fly.io/
  Render) was left open in `docs/PLAN.md` - pick one when this phase
  actually gets deployed, based on team familiarity/cost.
- **Registry + push credentials**: the CI `docker-build` job builds but
  doesn't push. Wiring it to a registry (ECR/Artifact Registry/GHCR) and
  adding the deploy step is provider-specific and needs credentials this
  repo doesn't have.
- **Managed Postgres/Redis**: e.g. RDS + ElastiCache, or Cloud SQL +
  Memorystore, or a single simpler provider. `DATABASE_URL`/
  `CELERY_BROKER_URL`/`CELERY_RESULT_BACKEND` (see `.env.example`) are how
  the app points at them - no code change needed either way.
- **Secrets**: `SECRET_KEY`, `DATABASE_URL`, `ADMIN_EMAILS`,
  `ALERT_WEBHOOK_URL`, etc. must come from the platform's secret manager
  (AWS Secrets Manager / GCP Secret Manager / provider env vars) at
  runtime - never baked into the image or committed as a real `.env`. The
  Dockerfile's `collectstatic` step uses obvious placeholder values for
  that build-time-only step specifically to make this obvious.

## Verifying locally

```
cp .env.example .env   # set SECRET_KEY and ALLOWED_HOSTS for this file
docker compose up --build
# then, in another shell:
docker compose exec web python manage.py createsuperuser
docker compose exec web python manage.py run_trading_cycle
docker compose exec web python manage.py sync_research   # Phase 7 feature build
```

Docker wasn't available in the environment this was built in, so the
compose file/Dockerfile are unverified by an actual build - review them
before relying on this in production, and expect to fix small issues on
a first real `docker compose up`.
