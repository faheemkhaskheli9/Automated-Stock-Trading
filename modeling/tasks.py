"""Celery tasks for the modeling app.

Unscheduled - like ``marketdata.tasks`` and ``execution.tasks``, wire a
``PeriodicTask`` (django-celery-beat, via admin) once this runs somewhere
Celery is actually deployed. Per-item failures are isolated so one bad
model/instrument never aborts the batch.
"""

import logging

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task
def train_model_task(model_id: int) -> int | None:
    from .models import TradingModel
    from .services import train_model

    model = TradingModel.objects.filter(pk=model_id).first()
    if model is None:
        logger.warning("train_model_task: no TradingModel %s", model_id)
        return None
    return train_model(model).pk


@shared_task
def run_model_predictions() -> list[int]:
    """Store a fresh prediction for every active model x its instruments."""
    from .models import TradingModel
    from .services import predict
    from .targets import derive_target_date

    today = timezone.localdate()
    prediction_ids: list[int] = []
    for model in TradingModel.objects.filter(is_active=True).exclude(artifact_path=""):
        target_date = derive_target_date(model.target_spec, today)
        for instrument in model.instruments.all():
            try:
                pred = predict(model, instrument, today, target_date=target_date)
            except Exception:  # noqa: BLE001 - isolate per instrument
                logger.exception(
                    "run_model_predictions failed for model=%s instrument=%s",
                    model.pk,
                    instrument.symbol,
                )
                continue
            prediction_ids.append(pred.pk)
    return prediction_ids


@shared_task
def backfill_prediction_actuals() -> int:
    from .services import backfill_actuals

    return backfill_actuals()
