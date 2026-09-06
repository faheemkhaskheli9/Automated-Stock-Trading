"""Run the ordered daily data-refresh chain in one process.

For the managed-scheduler deployment shape (docs/DEPLOYMENT.md, Option 2):
point EventBridge Scheduler / Cloud Scheduler at a single
``manage.py run_daily_pipeline`` container invocation instead of four
separately-triggered one-off tasks that would have to coordinate ordering.

Steps (from AutomaticStockTrading/schedules.py ``pipeline_jobs()``):
  1. sync_market_data           - marketdata.tasks.sync_all_active_instruments
  2. sync_research              - research.tasks.sync_all_research
  3. run_model_predictions      - modeling.tasks.run_model_predictions
  4. backfill_prediction_actuals- modeling.tasks.backfill_prediction_actuals

Each step is run in-process (the task functions, called synchronously - no
broker/worker). By default a failing step is logged and the chain
continues; the command still exits non-zero if any step failed. Use
``--fail-fast`` to stop at the first failure.
"""

import importlib
import logging
import time

from django.core.management.base import BaseCommand

from AutomaticStockTrading.schedules import pipeline_jobs

logger = logging.getLogger(__name__)


def _resolve(dotted: str):
    module_path, attr = dotted.rsplit(".", 1)
    return getattr(importlib.import_module(module_path), attr)


class Command(BaseCommand):
    help = "Run sync_market_data -> sync_research -> predictions -> backfill in order, in-process."

    def add_arguments(self, parser):
        parser.add_argument(
            "--fail-fast",
            action="store_true",
            help="Stop at the first failing step instead of continuing.",
        )
        parser.add_argument(
            "--only",
            action="append",
            metavar="JOB",
            help="Run only this job name (repeatable). Default: the full chain.",
        )
        parser.add_argument(
            "--skip",
            action="append",
            metavar="JOB",
            help="Skip this job name (repeatable).",
        )

    def handle(self, *args, **options):
        only = set(options.get("only") or [])
        skip = set(options.get("skip") or [])
        jobs = [j for j in pipeline_jobs() if (not only or j.name in only) and j.name not in skip]
        if not jobs:
            self.stdout.write(self.style.WARNING("No pipeline steps selected."))
            return

        failures = []
        attempted = 0
        for job in jobs:
            attempted += 1
            self.stdout.write(f"-> {job.name} ({job.task})")
            started = time.monotonic()
            try:
                result = _resolve(job.task)(**(job.kwargs or {}))
            except Exception as exc:  # noqa: BLE001 - one bad step shouldn't hide the rest
                logger.exception("run_daily_pipeline: step %s failed", job.name)
                failures.append(job.name)
                self.stderr.write(self.style.ERROR(f"   {job.name} FAILED: {exc!r}"))
                if options["fail_fast"]:
                    break
                continue
            elapsed = time.monotonic() - started
            self.stdout.write(self.style.SUCCESS(f"   ok ({elapsed:.1f}s): {result!r}"))

        if failures:
            raise SystemExit(
                self.style.ERROR(
                    f"{len(failures)}/{attempted} step(s) failed: {', '.join(failures)}"
                )
            )
        self.stdout.write(self.style.SUCCESS(f"Daily pipeline complete: {len(jobs)} step(s) ok."))
