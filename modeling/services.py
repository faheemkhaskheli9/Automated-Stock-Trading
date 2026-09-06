"""Thin orchestration layer shared by views, management commands and tasks.

Keeping the imports of ``training`` / ``prediction`` (which pull in
scikit-learn) inside the functions means importing ``modeling.services`` -
and therefore ``modeling.tasks`` at Celery autodiscovery - stays cheap.
"""

from __future__ import annotations


def train_model(model, *, start=None, end=None, created_by=None):
    from .training import train_model as _train

    return _train(model, start=start, end=end, created_by=created_by)


def predict(model, instrument, as_of, *, target_date=None, persist=True):
    from .prediction import predict as _predict

    return _predict(model, instrument, as_of, target_date=target_date, persist=persist)


def backfill_actuals(model=None) -> int:
    from .prediction import backfill_actuals as _backfill

    return _backfill(model)
