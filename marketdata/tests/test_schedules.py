"""Integrity checks for AutomaticStockTrading/schedules.py and its wiring."""

import importlib

from celery.schedules import crontab
from django.conf import settings
from django.test import TestCase

from AutomaticStockTrading import schedules


class ScheduleDefinitionTests(TestCase):
    def test_job_names_unique(self):
        names = [j.name for j in schedules.SCHEDULE]
        self.assertEqual(len(names), len(set(names)))

    def test_every_task_path_imports_and_is_callable(self):
        for job in schedules.SCHEDULE:
            module_path, attr = job.task.rsplit(".", 1)
            mod = importlib.import_module(module_path)
            self.assertTrue(hasattr(mod, attr), f"{job.task} missing")
            self.assertTrue(callable(getattr(mod, attr)), f"{job.task} not callable")

    def test_every_command_exists(self):
        from django.core.management import get_commands

        available = set(get_commands())
        for job in schedules.SCHEDULE:
            self.assertIn(job.command, available, f"{job.command!r} is not a management command")

    def test_pipeline_jobs_are_contiguously_ordered(self):
        jobs = schedules.pipeline_jobs()
        self.assertEqual([j.pipeline_order for j in jobs], list(range(1, len(jobs) + 1)))
        # The documented ordering: data in -> features -> predict -> backfill.
        self.assertEqual(
            [j.name for j in jobs],
            [
                "sync_market_data",
                "sync_research",
                "run_model_predictions",
                "backfill_prediction_actuals",
            ],
        )

    def test_non_pipeline_jobs_have_no_order(self):
        for job in schedules.SCHEDULE:
            if job.name not in {j.name for j in schedules.pipeline_jobs()}:
                self.assertIsNone(job.pipeline_order)


class BeatScheduleTests(TestCase):
    def test_settings_beat_schedule_is_built_from_schedule(self):
        bs = settings.CELERY_BEAT_SCHEDULE
        self.assertEqual(set(bs), {j.name for j in schedules.SCHEDULE})
        for job in schedules.SCHEDULE:
            entry = bs[job.name]
            self.assertEqual(entry["task"], job.task)
            self.assertIsInstance(entry["schedule"], crontab)

    def test_celery_timezone_follows_project_timezone(self):
        # Schedules are written in Asia/Karachi (PSX market hours); beat must
        # interpret them in the same zone.
        self.assertEqual(settings.CELERY_TIMEZONE, settings.TIME_ZONE)
        self.assertEqual(settings.TIME_ZONE, "Asia/Karachi")

    def test_cron_projection_round_trips_fields(self):
        c = schedules.Cron(minute="30", hour="8", day_of_week="mon")
        fields = c.to_beat_fields()
        self.assertEqual(fields["minute"], "30")
        self.assertEqual(fields["hour"], "8")
        self.assertEqual(fields["day_of_week"], "mon")
        cel = c.to_celery()
        self.assertIn(8, cel.hour)
        self.assertIn(30, cel.minute)


class ScheduleGuardTests(TestCase):
    def test_duplicate_name_is_rejected(self):
        dup = schedules.SCHEDULE + [schedules.SCHEDULE[0]]
        with self.assertRaises(ValueError):
            _validate(dup)

    def test_pipeline_order_gap_is_rejected(self):
        broken = [
            schedules.ScheduledJob(
                name="a",
                cron=schedules.Cron(),
                task="x.y",
                command="c",
                description="",
                pipeline_order=1,
            ),
            schedules.ScheduledJob(
                name="b",
                cron=schedules.Cron(),
                task="x.z",
                command="d",
                description="",
                pipeline_order=3,
            ),
        ]
        with self.assertRaises(ValueError):
            _validate(broken)


def _validate(schedule_list):
    """Re-run schedules._check_unique against an arbitrary list."""
    original = schedules.SCHEDULE
    try:
        schedules.SCHEDULE = schedule_list
        schedules._check_unique()
    finally:
        schedules.SCHEDULE = original
