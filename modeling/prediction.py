"""Load a trained artifact, build one point-in-time feature row, predict.

``predict`` is the only writer of ``ModelPrediction``. ``backfill_actuals``
fills ``actual_value`` / ``abs_error`` once the target session's bar exists,
feeding the accuracy view.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import joblib
import numpy as np
from django.conf import settings
from django.utils import timezone

from marketdata.models import PriceBar

from . import targets as target_mod
from .dataset import build_dataset
from .models import ModelPrediction

logger = logging.getLogger(__name__)


def _as_date(value) -> date:
    return value if isinstance(value, date) and not isinstance(value, datetime) else value.date()


def _feature_hash(names, values) -> str:
    payload = json.dumps(
        {"names": list(names), "values": [None if v is None else float(v) for v in values]},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def predict(model, instrument, as_of, *, target_date: date | None = None, persist: bool = True):
    if not model.artifact_path:
        raise ValueError("Model has no trained artifact - train it first")

    payload = joblib.load(model.artifact_path)
    as_of_date = _as_date(as_of)
    dataset = build_dataset(
        model, for_training=False, instruments=[instrument], single_row_as_of=as_of_date
    )
    if dataset.feature_names != payload["feature_names"]:
        raise ValueError(
            "The feature spec changed since this model was trained - retrain before predicting"
        )

    X = dataset.X.reindex(columns=payload["feature_names"])
    pipeline = payload["pipeline"]
    spec = target_mod.validate_spec(model.target_spec)
    raw = np.asarray(pipeline.predict(X))[0]

    predicted_value: float | None
    predicted_json = None
    if spec["type"] == "multistep":
        predicted_json = [float(v) for v in np.ravel(raw)]
        predicted_value = predicted_json[-1]
    elif spec["type"] == "direction":
        predicted_value = float(np.ravel(raw)[0])
        if hasattr(pipeline, "predict_proba"):
            predicted_json = {"proba_up": float(pipeline.predict_proba(X)[0, 1])}
    else:
        predicted_value = float(np.ravel(raw)[0])

    derived = target_mod.derive_target_date(model.target_spec, as_of_date)
    if derived is not None:
        target_date = derived
    if target_date is None:
        raise ValueError(
            "target_date is required for this target type (the app does not infer an "
            "exchange calendar)"
        )

    as_of_dt = dataset.X.index[0].to_pydatetime()
    feature_hash = _feature_hash(payload["feature_names"], X.iloc[0].tolist())

    if not persist:
        return ModelPrediction(
            model=model,
            instrument=instrument,
            as_of=as_of_dt,
            target_date=target_date,
            predicted_value=predicted_value,
            predicted_json=predicted_json,
            feature_hash=feature_hash,
        )

    obj, _ = ModelPrediction.objects.update_or_create(
        model=model,
        instrument=instrument,
        target_date=target_date,
        defaults={
            "as_of": as_of_dt,
            "predicted_value": predicted_value,
            "predicted_json": predicted_json,
            "feature_hash": feature_hash,
            "actual_value": None,
            "abs_error": None,
        },
    )
    return obj


# --------------------------------------------------------------------------
# Actuals backfill
# --------------------------------------------------------------------------
def _close_on(instrument, day: date, tz: str) -> float | None:
    zone = ZoneInfo(tz)
    lo = datetime.combine(day, time.min, tzinfo=zone)
    bar = (
        PriceBar.objects.filter(
            instrument=instrument,
            timeframe=PriceBar.Timeframe.DAILY,
            timestamp__gte=lo,
            timestamp__lt=lo + timedelta(days=1),
        )
        .order_by("timestamp")
        .first()
    )
    return float(bar.close) if bar else None


def _close_asof(instrument, moment: datetime) -> float | None:
    bar = (
        PriceBar.objects.filter(
            instrument=instrument,
            timeframe=PriceBar.Timeframe.DAILY,
            timestamp__lte=moment,
        )
        .order_by("-timestamp")
        .first()
    )
    return float(bar.close) if bar else None


def _actual_for(pred: ModelPrediction, spec: dict, tz: str) -> float | None:
    target_close = _close_on(pred.instrument, pred.target_date, tz)
    if target_close is None:
        return None
    ttype = spec["type"]
    if ttype in ("horizon_close", "weekday_anchored", "multistep"):
        return target_close
    base = _close_asof(pred.instrument, pred.as_of)
    if base is None or base == 0:
        return None
    if ttype == "horizon_return":
        return target_close / base - 1.0
    return 1.0 if target_close > base else 0.0  # direction


def backfill_actuals(model=None) -> int:
    tz = settings.TIME_ZONE
    now = timezone.now()
    qs = ModelPrediction.objects.filter(actual_value__isnull=True).select_related(
        "model", "instrument"
    )
    if model is not None:
        qs = qs.filter(model=model)

    filled = 0
    for pred in qs:
        if pred.target_date >= now.astimezone(ZoneInfo(tz)).date():
            continue
        try:
            spec = target_mod.validate_spec(pred.model.target_spec)
            actual = _actual_for(pred, spec, tz)
        except Exception:  # noqa: BLE001 - one bad row must not stop the batch
            logger.exception("backfill_actuals failed for prediction %s", pred.pk)
            continue
        if actual is None:
            continue
        pred.actual_value = actual
        if pred.predicted_value is not None:
            if spec["type"] == "direction":
                pred.abs_error = 0.0 if round(pred.predicted_value) == actual else 1.0
            else:
                pred.abs_error = abs(pred.predicted_value - actual)
        pred.save(update_fields=["actual_value", "abs_error"])
        filled += 1
    return filled
