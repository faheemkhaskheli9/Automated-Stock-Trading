---
name: add-scheduled-job
description: Wire a new recurring job (data sync, training, prediction, signal delivery) into the project's single schedule source of truth. Use when asked to schedule, automate, or run something periodically/on a cron in this trading app.
---

# Add a scheduled job

`AutomaticStockTrading/schedules.py` is the **single source of truth** for
every recurring job — don't hand-edit `settings.CELERY_BEAT_SCHEDULE` or add
a bare `PeriodicTask` in admin without also registering it here, or the two
scheduling shapes (Celery beat vs. a cloud managed scheduler) drift apart.

## Steps

1. **Write the job as a management command first**, calling into the
   owning app's `services.py` — never put real logic only in a Celery task.
   Every recurring job in this repo is "a plain management command that
   runs the same code with no broker/worker involved", per the deployment
   plan; the Celery task is a thin wrapper that calls the same service
   function (mirror `marketdata.tasks.sync_all_active_instruments` calling
   `marketdata.services.sync_active_instruments`, or `execution.tasks.
   run_trading_cycle`). Never raise on a single item's failure — log and
   continue, so one bad symbol/model doesn't abort the whole batch (every
   existing job follows this).
2. **Add a `Celery` task** in the owning app's `tasks.py` if one doesn't
   exist, calling the same service function.
3. **Register in `AutomaticStockTrading/schedules.py`**: add one
   `ScheduledJob` entry — crontab in `Asia/Karachi` (not UTC; PSX market
   hours), the task's dotted path, the equivalent management-command
   invocation, and `pipeline_order` if it must run relative to other jobs
   (e.g. after `sync_market_data`, before `run_model_predictions`).
4. **If it belongs in the daily chain** (`sync_market_data` →
   `sync_research` → `run_model_predictions` → `backfill_actuals`), insert it
   at the right `pipeline_order` so `python manage.py run_daily_pipeline`
   picks it up — don't create a second, parallel daily-chain concept.
5. **If it's a weekly `signalfeed` job** (train Sunday, send Monday
   pre-open, recap Friday post-close), follow that app's existing separate
   trigger pattern rather than folding it into the daily chain.
6. Run `python manage.py seed_periodic_tasks --dry-run` to confirm the new
   `django_celery_beat` `PeriodicTask` row (`schedules: <job>`) would be
   created correctly, then without `--dry-run` where Celery beat is actually
   used.
7. **Tests**: a test that the service function / management command
   tolerates a single bad item without raising (matches every sibling job's
   test), and that `schedules.py` produces the expected crontab for the new
   entry.
8. **Docs**: update the "Deployment" section note in `CLAUDE.md` /
   `docs/DEPLOYMENT.md` and the KB's `operations.md` with the new job.

## Verify

```
.venv/Scripts/python.exe -m pytest -k schedule -q
python manage.py run_daily_pipeline --only your_job   # if part of the daily chain
python manage.py seed_periodic_tasks --dry-run
```
