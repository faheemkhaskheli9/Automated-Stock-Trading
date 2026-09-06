"""Fit a configured :class:`TradingModel` and persist a joblib artifact.

``train_model`` never raises: every failure is recorded on the
``ModelTrainingRun`` row (``status="failed"`` + ``error``), mirroring the
per-item isolation in ``execution.tasks.run_trading_cycle``.
"""

from __future__ import annotations

import logging

import joblib
import numpy as np
from django.conf import settings
from django.utils import timezone
from sklearn.impute import SimpleImputer
from sklearn.multioutput import MultiOutputRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from . import metrics as metric_mod
from .dataset import build_dataset
from .estimators_base import TASK_CLASSIFICATION
from .models import ModelTrainingRun
from .registry import get_estimator

logger = logging.getLogger(__name__)


def _as_values(y):
    return y.to_numpy()


def build_pipeline(model, dataset) -> Pipeline:
    spec = get_estimator(model.estimator_key)
    estimator = spec.build(**(model.estimator_params or {}))

    if spec.baseline:
        anchor = spec.anchor_feature(model.estimator_params or {})
        if anchor not in dataset.feature_names:
            raise ValueError(
                f"Baseline estimator {model.estimator_key!r} needs feature {anchor!r} in the "
                "feature spec - add an 'ohlc' source that includes the matching close lag."
            )
        estimator.set_params(anchor_index=dataset.feature_names.index(anchor))

    if dataset.multioutput and not spec.multioutput:
        if dataset.task == TASK_CLASSIFICATION:
            raise ValueError("Multi-step targets are regression only")
        estimator = MultiOutputRegressor(estimator)

    steps = [("impute", SimpleImputer(strategy="median", keep_empty_features=True))]
    if spec.needs_scaling:
        steps.append(("scale", StandardScaler()))
    steps.append(("model", estimator))
    return Pipeline(steps)


def _score(pipeline, dataset) -> dict:
    pred = np.asarray(pipeline.predict(dataset.X))
    y = _as_values(dataset.y)
    anchor = dataset.anchor.to_numpy()
    proba = None
    if dataset.task == TASK_CLASSIFICATION and hasattr(pipeline, "predict_proba"):
        proba = np.asarray(pipeline.predict_proba(dataset.X))[:, 1]

    out = {}
    for name, mask in (("train", dataset.train_mask), ("holdout", dataset.holdout_mask)):
        if dataset.task == TASK_CLASSIFICATION:
            out[name] = metric_mod.classification_metrics(
                y[mask], pred[mask], y_proba=None if proba is None else proba[mask]
            )
        else:
            out[name] = metric_mod.regression_metrics(
                y[mask],
                pred[mask],
                anchor=None if dataset.multioutput else anchor[mask],
            )
    return out


def train_model(model, *, start=None, end=None, created_by=None) -> ModelTrainingRun:
    run = ModelTrainingRun.objects.create(model=model, created_by=created_by)
    try:
        dataset = build_dataset(model, start=start, end=end, for_training=True)
        pipeline = build_pipeline(model, dataset)
        pipeline.fit(dataset.X.iloc[dataset.train_mask], _as_values(dataset.y)[dataset.train_mask])

        scores = _score(pipeline, dataset)
        now = timezone.now()
        # The effective training cut-off this artifact actually saw. Frozen-
        # artifact backtesting needs it to know which later sessions are truly
        # out-of-sample - ``trained_at`` (wall clock) is not that boundary when
        # training was deliberately stopped at a past ``train_end``.
        effective_start = start or model.train_start
        effective_end = end or model.train_end
        artifact_path = settings.MODEL_ARTIFACT_DIR / f"model_{model.pk}_run_{run.pk}.joblib"
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {
                "pipeline": pipeline,
                "feature_names": dataset.feature_names,
                "feature_spec": model.feature_spec,
                "target_spec": model.target_spec,
                "estimator_key": model.estimator_key,
                "task": dataset.task,
                "multioutput": dataset.multioutput,
                "symbols": dataset.symbols,
                "trained_at": now.isoformat(),
                "train_start": effective_start.isoformat() if effective_start else None,
                "train_end": effective_end.isoformat() if effective_end else None,
            },
            artifact_path,
        )

        metrics = {
            **scores,
            "estimator": model.estimator_key,
            "target": model.target_spec,
            "symbols": dataset.symbols,
            "rows": {
                "train": int(dataset.train_mask.sum()),
                "holdout": int(dataset.holdout_mask.sum()),
            },
        }
        run.status = ModelTrainingRun.Status.SUCCESS
        run.finished_at = now
        run.rows = int(len(dataset.X))
        run.feature_count = len(dataset.feature_names)
        run.metrics = metrics
        run.artifact_path = str(artifact_path)
        run.save()

        model.artifact_path = str(artifact_path)
        model.metrics = metrics
        model.trained_at = now
        model.save(update_fields=["artifact_path", "metrics", "trained_at", "updated_at"])
    except Exception as exc:  # noqa: BLE001 - recorded on the run, never propagated
        logger.exception("Training failed for model %s", model.pk)
        run.status = ModelTrainingRun.Status.FAILED
        run.finished_at = timezone.now()
        run.error = f"{type(exc).__name__}: {exc}"
        run.save()
    return run
