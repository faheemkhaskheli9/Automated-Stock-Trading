from unittest import mock

import pytest

from modelsearch.models import ModelSearch, ModelSearchResult, ModelSearchRun
from modelsearch.search import COST_FIELDS, _dominated, pareto_flags, run_search
from modelsearch.tests.factories import make_instrument, make_price_series, make_search

pytestmark = pytest.mark.django_db


@pytest.fixture
def inst():
    obj = make_instrument("ENGRO")
    make_price_series(obj, n=340)
    return obj


def test_dataset_built_once_per_run(inst):
    search = make_search([inst])
    import modeling.dataset as ds_mod

    with mock.patch.object(ds_mod, "build_dataset", wraps=ds_mod.build_dataset) as spy:
        run = run_search(search)
    assert run.status == ModelSearchRun.Status.SUCCESS, run.error
    assert spy.call_count == 1


def test_results_ranked_and_costed(inst):
    search = make_search([inst])
    run = run_search(search)
    assert run.status == ModelSearchRun.Status.SUCCESS, run.error

    ok = list(ModelSearchResult.objects.filter(run=run, status="ok").order_by("rank"))
    assert [r.rank for r in ok] == list(range(1, len(ok) + 1))
    assert all(a.score >= b.score for a, b in zip(ok, ok[1:]))
    for r in ok:
        assert r.fit_seconds is not None and r.fit_seconds >= 0
        assert r.predict_latency_ms is not None and r.predict_latency_ms >= 0
        assert r.model_size_bytes and r.model_size_bytes > 0
    assert any(r.is_pareto for r in ok)

    search.refresh_from_db()
    assert search.best_result_id == ok[0].pk


def test_failing_candidate_is_isolated(inst):
    # Ridge with a negative alpha coerces + validates fine but sklearn rejects it at fit.
    search = make_search(
        [inst],
        search_space={
            "estimators": ["ridge"],
            "param_grids": {"ridge": {"alpha": [-1.0, 1.0]}},
        },
    )
    run = run_search(search)
    assert run.status == ModelSearchRun.Status.SUCCESS
    assert run.candidates_ok == 1 and run.candidates_failed == 1
    failed = ModelSearchResult.objects.get(run=run, status="failed")
    assert failed.error and failed.rank is None


def test_run_never_raises_when_dataset_cannot_be_built():
    empty = make_instrument("NOHIST")
    search = make_search([empty])
    run = run_search(search)  # no price history -> build_dataset raises
    assert run.status == ModelSearchRun.Status.FAILED
    assert "history" in run.error.lower() or run.error
    assert not ModelSearchResult.objects.filter(run=run).exists()


def test_walk_forward_mode_scores_via_pooled_folds(inst):
    search = make_search(
        [inst],
        search_space={"estimators": ["ridge"], "param_grids": {}},
        scoring_mode=ModelSearch.ScoringMode.WALK_FORWARD,
        wf_train_span=100,
        wf_test_span=20,
        wf_step=20,
        wf_gap=1,
    )
    run = run_search(search)
    assert run.status == ModelSearchRun.Status.SUCCESS, run.error

    result = ModelSearchResult.objects.get(run=run, status="ok")
    assert result.wf_folds and result.wf_folds > 1
    assert "holdout" in result.metrics and "holdout_score" in result.metrics
    # The walk-forward score is pooled over more rows than the single holdout.
    assert result.metrics["n"] > result.metrics["holdout"]["n"]
    # Ranking used the walk-forward score, not the stashed holdout one.
    assert result.score == pytest.approx(result.metrics["directional_accuracy"])


def test_walk_forward_mode_fails_run_when_history_too_short(inst):
    search = make_search(
        [inst],
        search_space={"estimators": ["ridge"], "param_grids": {}},
        scoring_mode=ModelSearch.ScoringMode.WALK_FORWARD,
        wf_train_span=1000,  # far more sessions than the fixture has
        wf_test_span=20,
        wf_step=20,
        wf_gap=1,
    )
    run = run_search(search)
    assert run.status == ModelSearchRun.Status.FAILED
    assert "walk-forward" in run.error.lower()
    assert not ModelSearchResult.objects.filter(run=run).exists()


def test_holdout_mode_is_still_the_default(inst):
    search = make_search([inst], search_space={"estimators": ["ridge"], "param_grids": {}})
    assert search.scoring_mode == ModelSearch.ScoringMode.HOLDOUT
    run = run_search(search)
    result = ModelSearchResult.objects.get(run=run, status="ok")
    assert result.wf_folds is None
    assert "holdout" not in result.metrics


def test_dominated_derives_all_cost_axes_from_cost_fields():
    """_dominated must compare every axis in COST_FIELDS (plus score), not a
    hand-typed subset - this catches the axes silently going out of sync if
    COST_FIELDS is ever extended without updating _dominated."""
    base = {"score": 1.0, **{f: 1.0 for f in COST_FIELDS}}
    for field in COST_FIELDS:
        worse = {**base, field: 2.0}  # strictly worse on exactly one cost axis
        assert _dominated(worse, [base, worse])
        assert not _dominated(base, [base, worse])


def test_pareto_flags_marks_non_dominated():
    rows = [
        {"score": 0.9, "fit_seconds": 1.0, "predict_latency_ms": 1.0, "model_size_bytes": 100},
        # dominated by row 0 on every axis
        {"score": 0.8, "fit_seconds": 2.0, "predict_latency_ms": 2.0, "model_size_bytes": 200},
        # cheaper but less accurate -> still on the frontier
        {"score": 0.7, "fit_seconds": 0.1, "predict_latency_ms": 0.1, "model_size_bytes": 10},
    ]
    assert pareto_flags(rows) == [True, False, True]
