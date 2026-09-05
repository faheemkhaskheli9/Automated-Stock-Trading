from datetime import date
from pathlib import Path

import pytest

from modeling.models import ModelTrainingRun, TradingModel
from modeling.services import train_model
from modeling.tests.factories import make_instrument, make_price_series

pytestmark = pytest.mark.django_db

OHLC = {"kind": "ohlc", "fields": ["open", "high", "low", "close"], "lags": [0, 1, 2]}
TECH = {"kind": "technical"}


def _model(instruments, estimator_key, target_spec, feature_spec=None, params=None):
    m = TradingModel.objects.create(
        name=f"{estimator_key}-{target_spec['type']}",
        estimator_key=estimator_key,
        estimator_params=params or {},
        feature_spec=feature_spec or [OHLC, {"kind": "return", "periods": [1, 5]}, TECH],
        target_spec=target_spec,
        train_end=date(2026, 1, 31),
    )
    m.instruments.set(instruments)
    return m


@pytest.fixture
def inst():
    obj = make_instrument("ENGRO")
    make_price_series(obj, n=380)
    return obj


@pytest.mark.parametrize("estimator_key", ["ridge", "random_forest", "hist_gbr", "naive_last"])
def test_regression_estimators_train_and_persist(inst, estimator_key):
    run = train_model(_model([inst], estimator_key, {"type": "horizon_close", "horizon": 1}))
    assert run.status == ModelTrainingRun.Status.SUCCESS, run.error
    assert Path(run.artifact_path).exists()
    assert run.metrics["holdout"]["mae"] > 0
    run.model.refresh_from_db()
    assert run.model.trained_at is not None
    assert run.model.artifact_path == run.artifact_path


def test_direction_target_with_logistic(inst):
    run = train_model(_model([inst], "logistic", {"type": "direction", "horizon": 1}))
    assert run.status == ModelTrainingRun.Status.SUCCESS, run.error
    assert "accuracy" in run.metrics["holdout"]


def test_multistep_native_and_wrapped(inst):
    native = train_model(_model([inst], "ridge", {"type": "multistep", "steps": 3}))
    wrapped = train_model(_model([inst], "gradient_boosting", {"type": "multistep", "steps": 3}))
    assert native.status == ModelTrainingRun.Status.SUCCESS, native.error
    assert wrapped.status == ModelTrainingRun.Status.SUCCESS, wrapped.error


def test_baseline_without_anchor_feature_fails_cleanly(inst):
    run = train_model(
        _model(
            [inst],
            "naive_last",
            {"type": "horizon_close", "horizon": 1},
            feature_spec=[{"kind": "return", "periods": [1]}],
        )
    )
    assert run.status == ModelTrainingRun.Status.FAILED
    assert "ohlc.close_lag_0" in run.error


def test_bad_estimator_param_is_recorded_not_raised(inst):
    run = train_model(
        _model([inst], "ridge", {"type": "horizon_close", "horizon": 1}, params={"alpha": "abc"})
    )
    assert run.status == ModelTrainingRun.Status.FAILED
    assert run.error


def test_weekday_anchored_trains(inst):
    run = train_model(
        _model(
            [inst],
            "ridge",
            {"type": "weekday_anchored", "entry_weekday": 0, "exit_weekday": 4},
        )
    )
    assert run.status == ModelTrainingRun.Status.SUCCESS, run.error
