"""Evaluate every candidate in a :class:`~modelsearch.models.ModelSearch`.

Reuses the ``modeling`` studio's machinery verbatim: ``build_dataset`` (built
**once** and shared across all candidates), ``build_pipeline`` and the
``metrics`` helpers. Two scoring modes (``ModelSearch.scoring_mode``):

* ``holdout`` (default) - one trailing split, same as before.
* ``walk_forward`` - reuses ``backtesting.walkforward.generate_folds`` to
  refit each candidate on every fold and pools the out-of-sample
  predicted-vs-actual into one metrics blob, mirroring how the ``backtesting``
  app scores a single ``TradingModel``. This is ``candidates x folds`` fits,
  so it costs more wall-clock than ``holdout`` - the holdout metrics/score are
  still computed and kept under ``metrics["holdout"]`` for comparison, since
  divergence between the two is exactly the case this mode exists for.

``run_search`` never raises: a failing candidate is recorded with
``status="failed"`` and the loop continues; a failure that kills the whole run
(e.g. the dataset cannot be built) lands on the ``ModelSearchRun`` row.
"""

from __future__ import annotations

import logging
import pickle
from dataclasses import dataclass
from time import perf_counter
from zoneinfo import ZoneInfo

import numpy as np
from django.conf import settings
from django.utils import timezone

from backtesting.walkforward import generate_folds

from . import spaces
from .models import ModelSearch, ModelSearchResult, ModelSearchRun

logger = logging.getLogger(__name__)

MIN_WF_TRAIN_ROWS = 10


@dataclass
class _Candidate:
    """Minimal stand-in for a ``TradingModel`` - all ``build_pipeline`` reads."""

    estimator_key: str
    estimator_params: dict


# Pareto cost axes - lower is better on each; "score" is the one
# higher-is-better axis. Adding a new cost dimension only means adding it
# here; _dominated() and the row-building call site both derive from it.
COST_FIELDS = ("fit_seconds", "predict_latency_ms", "model_size_bytes")


def _dominated(a: dict, others: list[dict]) -> bool:
    """True if some other candidate is >= on score and <= on every cost, and
    strictly better on at least one axis."""
    for b in others:
        if b is a:
            continue
        not_worse = b["score"] >= a["score"] and all(b[f] <= a[f] for f in COST_FIELDS)
        strictly_better = b["score"] > a["score"] or any(b[f] < a[f] for f in COST_FIELDS)
        if not_worse and strictly_better:
            return True
    return False


def pareto_flags(rows: list[dict]) -> list[bool]:
    """Per-row: True when the row is on the efficient frontier."""
    return [not _dominated(row, rows) for row in rows]


def _local_dates(index, tz):
    """Mirrors ``backtesting.engine._local_dates`` - local session dates for a
    tz-aware ``DatetimeIndex``, without importing that app's private helper."""
    return np.array(index.tz_convert(ZoneInfo(tz)).date)


def _score_candidate_walk_forward(
    candidate,
    dataset,
    folds,
    *,
    decision_dates,
    avail,
    y_all,
    anchor_all,
    is_clf,
    is_multi,
    score_key,
):
    """Refit ``candidate`` on every fold, pool the out-of-sample predictions,
    and score them as one blob - same idea as
    ``backtesting.engine._score_walk_forward``, minus the trade/equity
    translation this app has no use for. Mirrors the holdout branch below:
    fit/score on the raw (possibly multioutput) ``y``, anchor only used for
    single-output regression, same as ``anchor=None if dataset.multioutput``
    there.

    Returns ``(score, metrics, n_folds_used)``; ``(None, {}, 0)`` when no fold
    had enough training rows for this candidate.
    """
    from modeling.metrics import classification_metrics, regression_metrics
    from modeling.training import build_pipeline

    pooled_true, pooled_pred, pooled_anchor = [], [], []
    used = 0
    for fold in folds:
        test_mask = (decision_dates >= fold.test_start) & (decision_dates <= fold.test_end)
        if not test_mask.any():
            continue
        test_ts_min = dataset.X.index[test_mask].min()
        train_mask = (
            (decision_dates >= fold.train_start)
            & (decision_dates <= fold.train_end)
            & (avail <= test_ts_min).to_numpy()
        )
        if train_mask.sum() < MIN_WF_TRAIN_ROWS:
            continue

        train_idx = np.flatnonzero(train_mask)
        test_idx = np.flatnonzero(test_mask)

        pipeline = build_pipeline(candidate, dataset)
        pipeline.fit(dataset.X.iloc[train_idx], y_all[train_idx])
        pred = np.asarray(pipeline.predict(dataset.X.iloc[test_idx]))

        pooled_true.append(y_all[test_idx])
        pooled_pred.append(pred)
        if not is_multi:
            pooled_anchor.append(anchor_all[test_idx])
        used += 1

    if used == 0:
        return None, {}, 0

    pooled_true = np.concatenate(pooled_true, axis=0)
    pooled_pred = np.concatenate(pooled_pred, axis=0)
    if is_clf:
        metrics = classification_metrics(pooled_true, np.round(pooled_pred))
    else:
        anchor = np.concatenate(pooled_anchor, axis=0) if pooled_anchor else None
        metrics = regression_metrics(pooled_true, pooled_pred, anchor=anchor)
    return spaces.scalar_score(metrics, score_key), metrics, used


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

        is_walk_forward = search.scoring_mode == ModelSearch.ScoringMode.WALK_FORWARD
        wf_folds = []
        if is_walk_forward:
            decision_dates = _local_dates(dataset.X.index, settings.TIME_ZONE)
            sessions = sorted(set(decision_dates.tolist()))
            wf_folds = generate_folds(
                sessions,
                scheme=search.wf_scheme,
                train_span=search.wf_train_span,
                test_span=search.wf_test_span,
                step=search.wf_step,
                gap=search.wf_gap,
            )
            if not wf_folds:
                raise ValueError(
                    f"Only {len(sessions)} sessions of usable history - not enough for one "
                    f"{search.wf_train_span}+{search.wf_gap}+{search.wf_test_span} walk-forward "
                    "fold. Import more data, shrink the spans, or switch to holdout scoring."
                )
            avail = dataset.available_at
            anchor_all = dataset.anchor.to_numpy()

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
                holdout_score, holdout_metrics = score, metrics
                n_wf_folds = None

                if is_walk_forward:
                    wf_score, wf_metrics, n_wf_folds = _score_candidate_walk_forward(
                        _Candidate(key, params),
                        dataset,
                        wf_folds,
                        decision_dates=decision_dates,
                        avail=avail,
                        y_all=y,
                        anchor_all=anchor_all,
                        is_clf=task == "classification",
                        is_multi=dataset.multioutput,
                        score_key=score_key,
                    )
                    if wf_score is None:
                        raise ValueError(
                            "No walk-forward fold had enough training rows for this candidate"
                        )
                    score = wf_score
                    metrics = {
                        **wf_metrics,
                        "holdout": holdout_metrics,
                        "holdout_score": holdout_score,
                    }

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
                    wf_folds=n_wf_folds,
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
                [{"score": r.score, **{f: getattr(r, f) for f in COST_FIELDS}} for r in scored]
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
