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
```

Docker wasn't available in the environment this was built in, so the
compose file/Dockerfile are unverified by an actual build - review them
before relying on this in production, and expect to fix small issues on
a first real `docker compose up`.
