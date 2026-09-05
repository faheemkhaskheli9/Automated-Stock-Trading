"""Round-trip and leakage-guard tests for the regularised linear predictors."""

from copy import deepcopy
from datetime import date, datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from forecasting.base import PredictionFrame, TrainingFrame
from forecasting.features import assemble_prediction_frame, assemble_training_frame
from forecasting.linear import ElasticNetPredictor, RidgePredictor
from forecasting.registry import get_predictor_class, registered_keys
from research.tests.factories import make_instrument, make_price_series

ZONE = ZoneInfo("Asia/Karachi")


def local(day):
    return datetime(2026, 1, day, tzinfo=ZONE)


def make_inputs(closes, *, extra=None, start="2026-01-01"):
    index = pd.date_range(start, periods=len(closes), tz="Asia/Karachi")
    data = {"price.close": np.asarray(closes, dtype=float)}
    for name, values in (extra or {}).items():
        data[name] = np.asarray(values, dtype=float)
    frame_x = pd.DataFrame(data, index=index).sort_index(axis=1)
    return PredictionFrame(
        "ENGRO",
        "PSX",
        frame_x,
        pd.Series((index + pd.Timedelta(days=1)).date, index=index),
        pd.Series([f"hash-{i}" for i in range(len(closes))], index=index),
    )


def make_training(closes, ys, *, extra=None, start="2026-01-01"):
    inputs = make_inputs(closes, extra=extra, start=start)
    index = inputs.X.index
    return TrainingFrame(
        inputs,
        pd.Series(ys, index=index, dtype=float),
        pd.Series(index + pd.Timedelta(days=1), index=index),
    )


@pytest.fixture
def history():
    rng = np.random.default_rng(0)
    closes = 100.0 + np.cumsum(rng.normal(0.05, 0.6, 41))
    closes = np.abs(closes) + 50.0  # stay comfortably positive
    momentum = np.concatenate([[0.0], np.diff(closes[:-1])])
    return make_training(closes[:-1], closes[1:], extra={"tech.momentum": momentum})


def follow_on(history, closes, *, momentum=None):
    """A prediction frame that starts exactly at ``fitted_through``."""
    start = history.inputs.X.index.max() + pd.Timedelta(days=1)
    extra = {"tech.momentum": momentum if momentum is not None else [0.0] * len(closes)}
    return make_inputs(closes, extra=extra, start=start)


@pytest.fixture(params=[RidgePredictor, ElasticNetPredictor])
def predictor(request):
    return request.param()


def test_registration(predictor):
    assert {"ridge", "elasticnet"} <= set(registered_keys())
    assert get_predictor_class(predictor.key) is type(predictor)


def test_predict_series_round_trip(history, predictor):
    predictor.fit(history)
    frame = follow_on(history, [161.0, 162.5, 159.0], momentum=[1.0, 1.5, -3.5])
    result = predictor.predict_series(frame)
    assert len(result) == len(frame.X)
    assert all(p.predicted_close > 0 for p in result)
    assert [p.model_key for p in result] == [predictor.key] * 3
    assert [p.features_hash for p in result] == list(frame.features_hashes)
    assert [p.target_date for p in result] == list(frame.target_dates)
    assert all(p.lower is p.upper is p.confidence is None for p in result)
    # Row-independent: mutating a later row leaves earlier forecasts untouched.
    mutated = deepcopy(frame)
    mutated.X.iloc[-1] = [999.0, 5.0]
    assert predictor.predict_series(mutated)[:-1] == result[:-1]
    assert predictor.predict_series(frame) == result


def test_strong_regularisation_collapses_to_return_mean(history):
    predictor = RidgePredictor(alpha=1e12)
    predictor.fit(history)
    mean_return = float(
        (history.y.to_numpy() / history.inputs.X["price.close"].to_numpy() - 1.0).mean()
    )
    frame = follow_on(history, [140.0, 175.0], momentum=[2.0, -1.0])
    for prediction, close_now in zip(predictor.predict_series(frame), [140.0, 175.0]):
        assert prediction.predicted_close == pytest.approx(
            close_now * (1.0 + mean_return), rel=1e-3
        )


def test_fit_input_guards(history, predictor):
    with pytest.raises(TypeError, match="TrainingFrame"):
        predictor.fit(history.inputs)
    short = make_training([10.0, 11.0, 12.0, 13.0], [11.0, 12.0, 13.0, 14.0])
    with pytest.raises(ValueError, match="at least"):
        predictor.fit(short)
    bad = deepcopy(history)
    bad.inputs.X.iloc[0, bad.inputs.X.columns.get_loc("price.close")] = -1.0
    with pytest.raises(ValueError, match="finite and positive"):
        predictor.fit(bad)


def test_prediction_guards(history, predictor):
    frame = follow_on(history, [161.0])
    with pytest.raises(ValueError, match="Fit"):
        predictor.predict_series(frame)
    predictor.fit(history)
    with pytest.raises(TypeError, match="never training labels"):
        predictor.predict_series(history)
    assert predictor.predict_series(make_inputs([], start=frame.X.index[0])) == []
    with pytest.raises(ValueError, match="Training labels extend beyond"):
        predictor.predict_series(history.inputs)
    wrong = deepcopy(frame)
    wrong.symbol = "OTHER"
    with pytest.raises(ValueError, match="different instrument"):
        predictor.predict_series(wrong)
    dropped = deepcopy(frame)
    dropped.X = dropped.X.drop(columns=["tech.momentum"])
    with pytest.raises(ValueError, match="training schema"):
        predictor.predict_series(dropped)


def test_failed_refit_clears_state(history, predictor):
    predictor.fit(history)
    assert predictor._pipeline is not None
    broken = deepcopy(history)
    broken.inputs.X["price.close"] = np.nan
    with pytest.raises(ValueError, match="finite and positive"):
        predictor.fit(broken)
    assert predictor._pipeline is None


def test_fit_and_predict_over_assembled_frames(db, predictor):
    instrument = make_instrument()
    make_price_series(
        instrument,
        [100, 102, 101, 103, 105, 104, 106, 108, 107, 109],
        start=local(1),
    )
    train = assemble_training_frame("ENGRO", local(1), local(9), provider_keys=[])
    predictor.fit(train)
    frame = assemble_prediction_frame(
        "ENGRO", local(9), target_date=date(2026, 1, 9), provider_keys=[]
    )
    (prediction,) = predictor.predict_series(frame)
    assert prediction.predicted_close > 0
    assert prediction.model_key == predictor.key
    assert prediction.target_date == date(2026, 1, 9)
    assert len(prediction.features_hash) == 64
