"""Celery tasks for the signal feed.

Unscheduled - like ``modeling.tasks`` / ``execution.tasks``. Wire these to a
cloud managed scheduler (or a ``PeriodicTask``) where the app is deployed:
``train_weekly_models_task`` weekly, ``send_weekly_signals_task`` Monday
pre-open, ``recap_weekly_signals_task`` Friday post-close - all Asia/Karachi.
"""

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task
def train_weekly_models_task() -> list[int]:
    from .services import train_weekly_models

    return [r.pk for r in train_weekly_models()]


@shared_task
def send_weekly_signals_task(include_flat: bool = False) -> dict:
    from .services import send_weekly_signals

    summary = send_weekly_signals(include_flat=include_flat)
    return {k: v for k, v in summary.items() if k != "signals"}


@shared_task
def recap_weekly_signals_task() -> dict:
    from .services import recap_weekly_signals

    return recap_weekly_signals()
