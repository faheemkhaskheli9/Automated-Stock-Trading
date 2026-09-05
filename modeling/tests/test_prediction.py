from datetime import date

import pytest

from modeling.models import ModelPrediction, TradingModel
from modeling.services import backfill_actuals, predict, train_model
from modeling.tests.factories import make_instrument, make_price_series

pytestmark = pytest.mark.django_db

OHLC = {"kind": "ohlc", "fields": ["open", "high", "low", "close"], "lags": [0, 1, 2]}


@pytest.fixture
def trained():
    inst = make_instrument("ENGRO")
    make_price_series(inst, n=420)  # 2025-01-01 .. ~2026-02-24
    model = TradingModel.objects.create(
        name="close+1",
        estimator_key="ridge",
        feature_spec=[OHLC, {"kind": "return", "periods": [1, 5]}],
        target_spec={"type": "horizon_close", "horizon": 1},
        train_end=date(2026, 1, 15),
    )
    model.instruments.set([inst])
    run = train_model(model)
    assert run.status == run.Status.SUCCESS, run.error
    model.refresh_from_db()
    return model, inst


def test_predict_persists_row(trained):
    model, inst = trained
    pred = predict(model, inst, date(2026, 2, 1), target_date=date(2026, 2, 2))
    assert isinstance(pred, ModelPrediction)
    assert pred.predicted_value and pred.predicted_value > 0
    assert pred.target_date == date(2026, 2, 2)
    assert ModelPrediction.objects.count() == 1
    # re-predicting the same target upserts
    predict(model, inst, date(2026, 2, 1), target_date=date(2026, 2, 2))
    assert ModelPrediction.objects.count() == 1


def test_predict_requires_target_date_for_horizon(trained):
    model, inst = trained
    with pytest.raises(ValueError):
        predict(model, inst, date(2026, 2, 1))


def test_feature_spec_change_blocks_predict(trained):
    model, inst = trained
    model.feature_spec = model.feature_spec + [{"kind": "calendar", "features": ["weekday"]}]
    model.save()
    with pytest.raises(ValueError):
        predict(model, inst, date(2026, 2, 1), target_date=date(2026, 2, 2))


def test_backfill_actuals(trained):
    model, inst = trained
    predict(model, inst, date(2026, 2, 1), target_date=date(2026, 2, 2))
    filled = backfill_actuals(model)
    assert filled == 1
    pred = ModelPrediction.objects.get()
    assert pred.actual_value is not None
    assert pred.abs_error == pytest.approx(abs(pred.predicted_value - pred.actual_value))


def test_weekday_anchored_derives_target_date():
    inst = make_instrument("HBL")
    make_price_series(inst, n=420)
    model = TradingModel.objects.create(
        name="mon-fri",
        estimator_key="ridge",
        feature_spec=[OHLC],
        target_spec={"type": "weekday_anchored", "entry_weekday": 0, "exit_weekday": 4},
        train_end=date(2026, 1, 15),
    )
    model.instruments.set([inst])
    assert train_model(model).status == "success"
    model.refresh_from_db()
    pred = predict(model, inst, date(2026, 2, 2))  # 2026-02-02 is a Monday
    assert pred.target_date == date(2026, 2, 6)  # that Friday
