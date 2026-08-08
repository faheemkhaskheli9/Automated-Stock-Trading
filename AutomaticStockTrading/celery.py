"""Celery application for AutomaticStockTrading.

Scheduled jobs (market data updates, the trading cycle) are registered as
Celery Beat entries in later phases - see django_celery_beat, which stores
the schedule in the DB so it's manageable from the admin instead of code.
"""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "AutomaticStockTrading.settings.dev")

app = Celery("AutomaticStockTrading")

# Read CELERY_* settings from Django settings (see settings/base.py).
app.config_from_object("django.conf:settings", namespace="CELERY")

# Auto-discover tasks.py in each INSTALLED_APPS app.
app.autodiscover_tasks()
