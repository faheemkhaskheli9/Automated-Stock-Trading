"""Canonical schedule for every recurring job in the system.

This is the single source of truth consumed by both deployment shapes
(see ``docs/DEPLOYMENT.md``):

* **Persistent Celery** - ``settings.CELERY_BEAT_SCHEDULE`` is built from
  :data:`SCHEDULE` via :func:`beat_schedule`, so ``celery -A
  AutomaticStockTrading beat`` (DatabaseScheduler) picks these up with no
  manual admin step. ``manage.py seed_periodic_tasks`` additionally
  materialises them as ``django_celery_beat`` rows you can toggle in the
  admin.
* **Managed scheduler + one-off containers** (the plan's preferred shape) -
  point EventBridge Scheduler / Cloud Scheduler at the ``command`` of each
  entry (``manage.py <command>``); the daily data chain collapses into one
  ordered ``manage.py run_daily_pipeline`` invocation.

All times are in ``settings.TIME_ZONE`` (``Asia/Karachi`` - PSX market
hours), matching ``CELERY_TIMEZONE``. PSX closes ~15:30 PKT, so the daily
data refresh starts at 16:00 and the steps are staggered because ordering
matters: sync_market_data -> sync_research -> run_model_predictions ->
backfill_prediction_actuals.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from celery.schedules import crontab

# ``django_celery_beat`` PeriodicTask rows created by ``seed_periodic_tasks``
# are named ``<PERIODIC_TASK_PREFIX><job name>`` so the command can prune its
# own rows without touching hand-made ones.
PERIODIC_TASK_PREFIX = "schedules: "

WEEKDAYS = "mon,tue,wed,thu,fri"


@dataclass(frozen=True)
class Cron:
    """A crontab spec, expressed once and projected into both a Celery
    ``crontab`` object and ``django_celery_beat.CrontabSchedule`` fields."""

    minute: str = "0"
    hour: str = "*"
    day_of_week: str = "*"
    day_of_month: str = "*"
    month_of_year: str = "*"

    def to_celery(self) -> crontab:
        return crontab(
            minute=self.minute,
            hour=self.hour,
            day_of_week=self.day_of_week,
            day_of_month=self.day_of_month,
            month_of_year=self.month_of_year,
        )

    def to_beat_fields(self) -> dict[str, str]:
        return {
            "minute": self.minute,
            "hour": self.hour,
            "day_of_week": self.day_of_week,
            "day_of_month": self.day_of_month,
            "month_of_year": self.month_of_year,
        }

    def human(self) -> str:
        return (
            f"m={self.minute} h={self.hour} dow={self.day_of_week} "
            f"dom={self.day_of_month} mon={self.month_of_year}"
        )


@dataclass(frozen=True)
class ScheduledJob:
    name: str
    cron: Cron
    task: str
    command: str
    description: str
    kwargs: dict = field(default_factory=dict)
    #: Ordinal position in ``run_daily_pipeline`` (``None`` -> not part of the
    #: collapsed daily data chain; run on its own trigger).
    pipeline_order: int | None = None


# --- The schedule -----------------------------------------------------------

SCHEDULE: list[ScheduledJob] = [
    ScheduledJob(
        name="sync_market_data",
        cron=Cron(minute="0", hour="16", day_of_week=WEEKDAYS),
        task="marketdata.tasks.sync_all_active_instruments",
        command="sync_market_data",
        description="Refresh PriceBar history for active instruments after PSX close.",
        pipeline_order=1,
    ),
    ScheduledJob(
        name="sync_research",
        cron=Cron(minute="20", hour="16", day_of_week=WEEKDAYS),
        task="research.tasks.sync_all_research",
        command="sync_research",
        description="Ingest news feeds and rebuild point-in-time ResearchSnapshot bundles.",
        pipeline_order=2,
    ),
    ScheduledJob(
        name="run_model_predictions",
        cron=Cron(minute="40", hour="16", day_of_week=WEEKDAYS),
        task="modeling.tasks.run_model_predictions",
        command="run_model_predictions",
        description="Write next-session ModelPrediction rows for every active TradingModel.",
        pipeline_order=3,
    ),
    ScheduledJob(
        name="backfill_prediction_actuals",
        cron=Cron(minute="0", hour="17", day_of_week=WEEKDAYS),
        task="modeling.tasks.backfill_prediction_actuals",
        command="backfill_actuals",
        description="Fill realised closes onto past ModelPredictions once their session closed.",
        pipeline_order=4,
    ),
    ScheduledJob(
        name="run_trading_cycle",
        cron=Cron(minute="0", hour="11", day_of_week=WEEKDAYS),
        task="execution.tasks.run_trading_cycle",
        command="run_trading_cycle",
        description="Generate signals and place paper orders for active Strategies (market hours).",
    ),
    ScheduledJob(
        name="train_weekly_models",
        cron=Cron(minute="0", hour="6", day_of_week="sun"),
        task="signalfeed.tasks.train_weekly_models_task",
        command="train_weekly_models",
        description="Retrain every modeling.TradingModel referenced by an active WatchItem.",
    ),
    ScheduledJob(
        name="send_weekly_signals",
        cron=Cron(minute="30", hour="8", day_of_week="mon"),
        task="signalfeed.tasks.send_weekly_signals_task",
        command="send_weekly_signals",
        description="Build and push this week's Mon->Fri WeeklySignal calls (pre-open).",
    ),
    ScheduledJob(
        name="recap_weekly_signals",
        cron=Cron(minute="0", hour="17", day_of_week="fri"),
        task="signalfeed.tasks.recap_weekly_signals_task",
        command="recap_weekly_signals",
        description="Grade the week's signals and send the hit-rate recap (post-close).",
    ),
]


def _check_unique() -> None:
    names = [j.name for j in SCHEDULE]
    dupes = {n for n in names if names.count(n) > 1}
    if dupes:
        raise ValueError(f"Duplicate ScheduledJob name(s): {sorted(dupes)}")
    orders = [j.pipeline_order for j in SCHEDULE if j.pipeline_order is not None]
    if sorted(orders) != list(range(1, len(orders) + 1)):
        raise ValueError(f"pipeline_order must be a 1..N run with no gaps/dupes, got {orders}")


_check_unique()


def beat_schedule() -> dict:
    """Build the ``settings.CELERY_BEAT_SCHEDULE`` mapping from :data:`SCHEDULE`."""
    out: dict = {}
    for job in SCHEDULE:
        entry: dict = {"task": job.task, "schedule": job.cron.to_celery()}
        if job.kwargs:
            entry["kwargs"] = dict(job.kwargs)
        out[job.name] = entry
    return out


def pipeline_jobs() -> list[ScheduledJob]:
    """The daily data chain, in execution order, for ``run_daily_pipeline``."""
    return sorted(
        (j for j in SCHEDULE if j.pipeline_order is not None),
        key=lambda j: j.pipeline_order,
    )
