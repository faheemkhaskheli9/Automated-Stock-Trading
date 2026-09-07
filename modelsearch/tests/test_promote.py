import pytest

from modeling.models import ModelTrainingRun, TradingModel
from modeling.services import train_model
from modelsearch.search import run_search
from modelsearch.services import promote_result
from modelsearch.tests.factories import (
    FEATURE_SPEC,
    TARGET_SPEC,
    make_instrument,
    make_price_series,
    make_search,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def inst():
    obj = make_instrument("ENGRO")
    make_price_series(obj, n=340)
    return obj


def test_promote_creates_trainable_model(inst):
    search = make_search([inst])
    run = run_search(search)
    best = search.all_results.get(run=run, rank=1)

    model = promote_result(best, name="promoted")
    assert isinstance(model, TradingModel)
    assert model.estimator_key == best.estimator_key
    assert model.estimator_params == best.estimator_params
    assert model.feature_spec == FEATURE_SPEC
    assert model.target_spec == TARGET_SPEC
    assert list(model.instruments.all()) == [inst]

    training = train_model(model)
    assert training.status == ModelTrainingRun.Status.SUCCESS, training.error


def test_promote_default_name(inst):
    search = make_search([inst])
    run = run_search(search)
    best = search.all_results.get(run=run, rank=1)
    model = promote_result(best)
    assert model.name == f"{search.name} · {best.estimator_key}"
