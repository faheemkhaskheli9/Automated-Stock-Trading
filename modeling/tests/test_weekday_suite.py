import pytest

from modeling.models import TradingModel
from modeling.tests.factories import make_instrument, make_price_series
from modeling.weekday_suite import (
    TARGET_SPEC,
    build_weekday_suite,
    evaluate_suite,
    suite_estimator_keys,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def rich_instrument():
    inst = make_instrument("ENGRO")
    make_price_series(inst, n=400)
    return inst


def test_suite_estimator_keys_excludes_meta_estimators_and_classifiers():
    keys = suite_estimator_keys()
    assert "voting_ensemble" not in keys
    assert "stacking_ensemble" not in keys
    assert "logistic" not in keys
    assert "ridge" in keys
    assert "naive_last" in keys  # baseline kept in as the yardstick


def test_build_weekday_suite_trains_one_model_per_estimator(rich_instrument):
    keys = suite_estimator_keys()
    result = build_weekday_suite(rich_instrument, estimators=keys)

    assert result.errors == []
    assert result.instrument == rich_instrument
    assert {m.estimator_key for m in result.models} == set(keys)
    for model in result.models:
        assert model.target_spec == TARGET_SPEC
        assert model.trained_at is not None
        assert list(model.instruments.all()) == [rich_instrument]

    assert len(result.evaluation) == len(keys)
    ranks = [row["rank"] for row in result.evaluation]
    assert ranks == sorted(ranks)


def test_build_weekday_suite_is_idempotent_on_model_names(rich_instrument):
    build_weekday_suite(rich_instrument, estimators=["ridge"])
    build_weekday_suite(rich_instrument, estimators=["ridge"])
    assert TradingModel.objects.filter(estimator_key="ridge").count() == 1


def test_build_weekday_suite_auto_picks_symbol_when_none_given(rich_instrument):
    result = build_weekday_suite(estimators=["ridge"])
    assert result.instrument == rich_instrument
    assert result.symbol_score.viable is True


def test_build_weekday_suite_reports_error_when_nothing_viable():
    make_instrument("THIN")  # no price bars at all
    result = build_weekday_suite(estimators=["ridge"])
    assert result.models == []
    assert result.errors


def test_build_weekday_suite_skips_unknown_estimator_key(rich_instrument):
    result = build_weekday_suite(rich_instrument, estimators=["ridge", "not-a-real-key"])
    assert any("not-a-real-key" in e for e in result.errors)
    assert {m.estimator_key for m in result.models} == {"ridge"}


def test_evaluate_suite_ranks_by_skill_and_handles_missing_metrics():
    class FakeModel:
        def __init__(self, key, metrics, trained_at="x"):
            self.estimator_key = key
            self.metrics = metrics
            self.trained_at = trained_at

    good = FakeModel("ridge", {"holdout": {"n": 10, "mae": 1.0, "skill_vs_naive": 0.5}})
    bad = FakeModel("drift", {"holdout": {"n": 10, "mae": 5.0, "skill_vs_naive": -0.2}})
    unscored = FakeModel("mlp", {}, trained_at=None)

    rows = evaluate_suite([bad, unscored, good])
    assert [r["estimator"] for r in rows] == ["ridge", "drift", "mlp"]
    assert rows[-1]["status"] == "failed"
