"""Materialise AutomaticStockTrading/schedules.py as django_celery_beat rows.

For the persistent-Celery deployment shape (docs/DEPLOYMENT.md, Option 1)
when you want PeriodicTask rows you can toggle/inspect in the admin. The
DatabaseScheduler already syncs ``settings.CELERY_BEAT_SCHEDULE`` on beat
startup, so this command is optional - it just makes the rows explicit and
survives independently of the beat process.

Idempotent: re-running updates the crontab/description in place. Rows this
command owns are named ``schedules: <job name>`` (PERIODIC_TASK_PREFIX).
"""

import json

from django.conf import settings
from django.core.management.base import BaseCommand

from AutomaticStockTrading.schedules import PERIODIC_TASK_PREFIX, SCHEDULE


class Command(BaseCommand):
    help = "Create/update django_celery_beat PeriodicTask rows from schedules.py."

    def add_arguments(self, parser):
        parser.add_argument(
            "--disabled",
            action="store_true",
            help="Create/refresh the rows but leave them disabled (enabled=False).",
        )
        parser.add_argument(
            "--prune",
            action="store_true",
            help="Delete owned rows whose job no longer exists in schedules.py.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change without writing.",
        )

    def handle(self, *args, **options):
        from django_celery_beat.models import CrontabSchedule, PeriodicTask

        dry_run = options["dry_run"]
        enabled = not options["disabled"]
        tz = settings.TIME_ZONE

        seen_names = set()
        for job in SCHEDULE:
            name = f"{PERIODIC_TASK_PREFIX}{job.name}"
            seen_names.add(name)
            fields = job.cron.to_beat_fields()

            if dry_run:
                self.stdout.write(f"would upsert {name!r}: {job.task} @ {job.cron.human()} tz={tz}")
                continue

            crontab, _ = CrontabSchedule.objects.get_or_create(timezone=tz, **fields)
            _, created = PeriodicTask.objects.update_or_create(
                name=name,
                defaults={
                    "task": job.task,
                    "crontab": crontab,
                    "interval": None,
                    "kwargs": json.dumps(job.kwargs or {}),
                    "description": job.description,
                    "enabled": enabled,
                },
            )
            verb = "created" if created else "updated"
            self.stdout.write(f"  {verb} {name!r} -> {job.task} @ {job.cron.human()}")

        if options["prune"]:
            stale = PeriodicTask.objects.filter(name__startswith=PERIODIC_TASK_PREFIX).exclude(
                name__in=seen_names
            )
            for task in stale:
                if dry_run:
                    self.stdout.write(f"would prune {task.name!r}")
                else:
                    task.delete()
                    self.stdout.write(f"  pruned {task.name!r}")

        if not dry_run:
            self._cleanup_orphan_crontabs(CrontabSchedule, PeriodicTask)
            self.stdout.write(
                self.style.SUCCESS(f"Seeded {len(SCHEDULE)} periodic task(s) (tz={tz}).")
            )

    @staticmethod
    def _cleanup_orphan_crontabs(CrontabSchedule, PeriodicTask):
        used = set(
            PeriodicTask.objects.exclude(crontab__isnull=True).values_list("crontab_id", flat=True)
        )
        CrontabSchedule.objects.exclude(id__in=used).delete()
