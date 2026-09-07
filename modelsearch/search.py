"""Evaluate every candidate in a :class:`~modelsearch.models.ModelSearch`.

Reuses the ``modeling`` studio's machinery verbatim: ``build_dataset`` (built
**once** and shared across all candidates), ``build_pipeline`` and the
``metrics`` helpers. Only the trailing holdout is scored - this is not
walk-forward (that is the ``backtesting`` app).

``run_search`` never raises: a failing candidate is recorded with
``status="failed"`` and the loop continues; a failure that kills the whole run
(e.g. the dataset cannot be built) lands on the ``ModelSearchRun`` row.
"""

from __future__ import annotations

import logging
import pickle
from dataclasses import dataclass
from time import perf_counter

import numpy as np
from django.utils import timezone

from . import spaces
from .models import ModelSearchResult, ModelSearchRun

logger = logging.getLogger(__name__)


@dataclass
class _Candidate:
    """Minimal stand-in for a ``TradingModel`` - all ``build_pipeline`` reads."""

    estimator_key: str
    estimator_params: dict


def _dominated(a: dict, others: list[dict]) -> bool:
    """True if some other candidate is >= on score and <= on every cost, and
    strictly better on at least one axis."""
    for b in others:
        if b is a:
            continue
        not_worse = (
            b["score"] >= a["score"]
            and b["fit_seconds"] <= a["fit_seconds"]
            and b["predict_latency_ms"] <= a["predict_latency_ms"]
            and b["model_size_bytes"] <= a["model_size_bytes"]
        )
        strictly_better = (
            b["score"] > a["score"]
            or b["fit_seconds"] < a["fit_seconds"]
            or b["predict_latency_ms"] < a["predict_latency_ms"]
            or b["model_size_bytes"] < a["model_size_bytes"]
        )
        if not_worse and strictly_better:
            return True
    return False


def pareto_flags(rows: list[dict]) -> list[bool]:
    """Per-row: True when the row is on the efficient frontier."""
    return [not _dominated(row, rows) for row in rows]


def run_search(search, *, created_by=None) -> ModelSearchRun:
    from modeling.dataset import build_dataset
    from modeling.metrics import classification_metrics, regression_metrics
    from modeling.training import build_pipeline

    run = ModelSearchRun.objects.create(search=search, created_by=created_by)
    try:
        candidates = spaces.expand(
            search.search_space,
            mode=search.mode,
            max_candidates=search.max_candidates,
            seed=search.random_seed,
        )
        if not candidates:
            raise ValueError("The search space expanded to zero candidates.")

        dataset = build_dataset(search, for_training=True)
        task = dataset.task
        score_key = search.scoring or spaces.DEFAULT_SCORE[task]

        y = dataset.y.to_numpy()
        train_mask, hold_mask = dataset.train_mask, dataset.holdout_mask
        x_train, x_hold = dataset.X.iloc[train_mask], dataset.X.iloc[hold_mask]
        y_train, y_hold = y[train_mask], y[hold_mask]
        anchor_hold = dataset.anchor.to_numpy()[hold_mask]
        n_hold = max(int(hold_mask.sum()), 1)

        rows: list[ModelSearchResult] = []
        scored: list[ModelSearchResult] = []
        for key, params in candidates:
            digest = spaces.params_hash(key, params)
            try:
                pipeline = build_pipeline(_Candidate(key, params), dataset)

                t0 = perf_counter()
                pipeline.fit(x_train, y_train)
                fit_seconds = perf_counter() - t0

                t0 = perf_counter()
                pred = np.asarray(pipeline.predict(x_hold))
                predict_seconds = perf_counter() - t0

                if task == "classification":
                    proba = None
                    if hasattr(pipeline, "predict_proba"):
                        proba = np.asarray(pipeline.predict_proba(x_hold))[:, 1]
                    metrics = classification_metrics(y_hold, pred, y_proba=proba)
                else:
                    metrics = regression_metrics(
                        y_hold, pred, anchor=None if dataset.multioutput else anchor_hold
                    )

                size = len(pickle.dumps(pipeline.named_steps["model"]))
                score = spaces.scalar_score(metrics, score_key)
                row = ModelSearchResult(
                    search=search,
                    run=run,
                    estimator_key=key,
                    estimator_params=params,
                    params_hash=digest,
                    status=ModelSearchResult.Status.OK,
                    score=score,
                    metrics=metrics,
                    fit_seconds=fit_seconds,
                    predict_seconds=predict_seconds,
                    predict_latency_ms=predict_seconds / n_hold * 1000.0,
                    model_size_bytes=size,
                )
                rows.append(row)
                if score is not None and np.isfinite(score):
                    scored.append(row)
            except Exception as exc:  # noqa: BLE001 - recorded per candidate
                logger.exception("model search candidate %s %s failed", key, params)
                rows.append(
                    ModelSearchResult(
                        search=search,
                        run=run,
                        estimator_key=key,
                        estimator_params=params,
                        params_hash=digest,
                        status=ModelSearchResult.Status.FAILED,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )

        scored.sort(key=lambda r: r.score, reverse=True)
        for i, row in enumerate(scored, start=1):
            row.rank = i
        if scored:
            frontier = pareto_flags(
                [
                    {
                        "score": r.score,
                        "fit_seconds": r.fit_seconds,
                        "predict_latency_ms": r.predict_latency_ms,
                        "model_size_bytes": r.model_size_bytes,
                    }
                    for r in scored
                ]
            )
            for row, flag in zip(scored, frontier):
                row.is_pareto = flag

        ModelSearchResult.objects.bulk_create(rows)

        ok = sum(1 for r in rows if r.status == ModelSearchResult.Status.OK)
        run.status = ModelSearchRun.Status.SUCCESS
        run.finished_at = timezone.now()
        run.candidates_total = len(candidates)
        run.candidates_ok = ok
        run.candidates_failed = len(rows) - ok
        run.dataset_rows = int(len(dataset.X))
        run.feature_count = len(dataset.feature_names)
        run.save()

        best = ModelSearchResult.objects.filter(run=run, rank=1).first()
        if best is not None:
            search.best_result = best
            search.save(update_fields=["best_result", "updated_at"])
    except Exception as exc:  # noqa: BLE001 - recorded on the run, never propagated
        logger.exception("model search failed for search %s", search.pk)
        run.status = ModelSearchRun.Status.FAILED
        run.finished_at = timezone.now()
        run.error = f"{type(exc).__name__}: {exc}"
        run.save()
    return run
