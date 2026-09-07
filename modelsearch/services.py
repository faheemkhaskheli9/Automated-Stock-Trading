"""Thin orchestration layer shared by views, the management command and the
Celery task. Heavy imports (scikit-learn, ``modeling.training``) stay inside the
functions so importing ``modelsearch.services`` - and ``modelsearch.tasks`` at
Celery autodiscovery - stays cheap.
"""

from __future__ import annotations


def run_search(search, *, created_by=None):
    from .search import run_search as _run

    return _run(search, created_by=created_by)


def promote_result(result, *, name=None, activate=False):
    """Create a new ``modeling.TradingModel`` from a winning candidate.

    Copies the search's feature/target spec, instruments and train window;
    takes the estimator key + params from ``result``. Does **not** train it -
    the operator does that from the normal ``/modeling/`` detail page.
    """
    from modeling.models import TradingModel

    search = result.search
    model = TradingModel(
        name=name or f"{search.name} · {result.estimator_key}",
        estimator_key=result.estimator_key,
        estimator_params=result.estimator_params or {},
        feature_spec=search.feature_spec,
        target_spec=search.target_spec,
        train_start=search.train_start,
        train_end=search.train_end,
        holdout_fraction=search.holdout_fraction,
        is_active=activate,
    )
    model.full_clean(exclude=["instruments"])
    model.save()
    model.instruments.set(search.instruments.all())
    return model
