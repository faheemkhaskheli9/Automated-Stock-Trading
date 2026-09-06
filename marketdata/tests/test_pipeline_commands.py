"""Tests for the scheduler-wiring management commands:
``seed_periodic_tasks`` and ``run_daily_pipeline``.
"""

import json
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from AutomaticStockTrading import schedules
from AutomaticStockTrading.schedules import PERIODIC_TASK_PREFIX


class SeedPeriodicTasksTests(TestCase):
    def _owned(self):
        from django_celery_beat.models import PeriodicTask

        return PeriodicTask.objects.filter(name__startswith=PERIODIC_TASK_PREFIX)

    def test_creates_one_row_per_job(self):
        call_command("seed_periodic_tasks", stdout=StringIO())

        rows = {t.name: t for t in self._owned()}
        self.assertEqual(set(rows), {f"{PERIODIC_TASK_PREFIX}{j.name}" for j in schedules.SCHEDULE})
        row = rows[f"{PERIODIC_TASK_PREFIX}send_weekly_signals"]
        self.assertEqual(row.task, "signalfeed.tasks.send_weekly_signals_task")
        self.assertEqual(row.crontab.hour, "8")
        self.assertEqual(row.crontab.minute, "30")
        self.assertEqual(row.crontab.day_of_week, "mon")
        self.assertEqual(row.crontab.timezone.key, "Asia/Karachi")
        self.assertEqual(json.loads(row.kwargs), {})
        self.assertTrue(row.enabled)

    def test_idempotent(self):
        call_command("seed_periodic_tasks", stdout=StringIO())
        first = {t.pk for t in self._owned()}
        call_command("seed_periodic_tasks", stdout=StringIO())
        second = {t.pk for t in self._owned()}

        self.assertEqual(first, second)
        self.assertEqual(len(second), len(schedules.SCHEDULE))

    def test_disabled_flag(self):
        call_command("seed_periodic_tasks", "--disabled", stdout=StringIO())
        self.assertTrue(all(not t.enabled for t in self._owned()))

    def test_prune_removes_stale_owned_rows(self):
        from django_celery_beat.models import CrontabSchedule, PeriodicTask

        cron = CrontabSchedule.objects.create(minute="0", hour="0")
        PeriodicTask.objects.create(name=f"{PERIODIC_TASK_PREFIX}gone", task="x.y.z", crontab=cron)
        call_command("seed_periodic_tasks", "--prune", stdout=StringIO())

        self.assertFalse(PeriodicTask.objects.filter(name=f"{PERIODIC_TASK_PREFIX}gone").exists())

    def test_dry_run_writes_nothing(self):
        call_command("seed_periodic_tasks", "--dry-run", stdout=StringIO())
        self.assertEqual(self._owned().count(), 0)


class RunDailyPipelineTests(TestCase):
    def setUp(self):
        self.calls = []
        # Replace the dotted-path resolver with a factory of recording fakes.
        import marketdata.management.commands.run_daily_pipeline as mod

        self._mod = mod
        self._orig = mod._resolve

        def fake_resolve(dotted, _log=self.calls):
            def _fake(**kwargs):
                _log.append((dotted, kwargs))
                return f"ran {dotted}"

            return _fake

        mod._resolve = fake_resolve
        self.addCleanup(setattr, mod, "_resolve", self._orig)

    def test_runs_full_chain_in_order(self):
        out = StringIO()
        call_command("run_daily_pipeline", stdout=out, stderr=StringIO())

        self.assertEqual(
            [c[0] for c in self.calls],
            [j.task for j in schedules.pipeline_jobs()],
        )
        self.assertIn("Daily pipeline complete", out.getvalue())

    def test_only_and_skip_filters(self):
        call_command("run_daily_pipeline", only=["sync_research"], stdout=StringIO())
        self.assertEqual([c[0] for c in self.calls], ["research.tasks.sync_all_research"])

        self.calls.clear()
        call_command("run_daily_pipeline", skip=["sync_market_data"], stdout=StringIO())
        self.assertNotIn("marketdata.tasks.sync_all_active_instruments", [c[0] for c in self.calls])
        self.assertEqual(len(self.calls), len(schedules.pipeline_jobs()) - 1)

    def test_continues_past_a_failing_step_and_exits_nonzero(self):
        def boom_resolve(dotted, _log=self.calls):
            def _fake(**kwargs):
                _log.append((dotted, kwargs))
                if dotted == "research.tasks.sync_all_research":
                    raise RuntimeError("nope")
                return "ok"

            return _fake

        self._mod._resolve = boom_resolve

        with self.assertRaises(SystemExit):
            call_command("run_daily_pipeline", stdout=StringIO(), stderr=StringIO())

        # All four steps still attempted despite step 2 failing.
        self.assertEqual(len(self.calls), len(schedules.pipeline_jobs()))

    def test_fail_fast_stops_at_first_failure(self):
        def boom_resolve(dotted, _log=self.calls):
            def _fake(**kwargs):
                _log.append((dotted, kwargs))
                raise RuntimeError("nope")

            return _fake

        self._mod._resolve = boom_resolve

        with self.assertRaises(SystemExit):
            call_command("run_daily_pipeline", "--fail-fast", stdout=StringIO(), stderr=StringIO())

        self.assertEqual(len(self.calls), 1)
