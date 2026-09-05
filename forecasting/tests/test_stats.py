from copy import deepcopy
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from forecasting.base import PredictionFrame, TrainingFrame
from forecasting.registry import get_predictor_class
from forecasting.stats import EtsPredictor, SarimaPredictor


def inputs(values, start="2026-01-01"):
    index = pd.date_range(start, periods=len(values), tz="Asia/Karachi")
    return PredictionFrame(
        "ENGRO",
        "PSX",
        pd.DataFrame({"price.close": values}, index=index),
        pd.Series((index + pd.Timedelta(days=1)).date, index=index),
        pd.Series([f"hash-{i}" for i in range(len(values))], index=index),
    )


@pytest.fixture
def history():
    values = 100 + np.arange(41) * 0.2 + np.sin(np.arange(41))
    frame = inputs(values[:-1])
    return TrainingFrame(
        frame,
        pd.Series(values[1:], index=frame.X.index),
        pd.Series(frame.X.index + pd.Timedelta(days=1), index=frame.X.index),
    )


@pytest.fixture(params=[SarimaPredictor, EtsPredictor])
def predictor(request):
    return request.param()


def test_registration(predictor):
    assert get_predictor_class(predictor.key) is type(predictor)


def test_replay_is_prefix_only_repeatable_and_does_not_refit(history, predictor):
    predictor.fit(history)
    frame = inputs([history.y.iloc[-1], 111, 112], start=history.target_available_at.iloc[-1])
    parameters = predictor._parameters.copy()
    # A prediction may smooth with fitted parameters, but may never fit.
    model_type = type(predictor._model(predictor._values))
    with patch.object(model_type, "fit", side_effect=AssertionError("inference refit")):
        result = predictor.predict_series(frame)
        changed = deepcopy(frame)
        changed.X.iloc[-1, 0] = 999
        assert predictor.predict_series(changed)[:2] == result[:2]
        assert predictor.predict_series(frame) == result
    np.testing.assert_array_equal(parameters, predictor._parameters)
    assert len(result) == len(frame.X)
    assert all(p.predicted_close > 0 for p in result)
    assert [p.features_hash for p in result] == list(frame.features_hashes)
    assert [p.target_date for p in result] == list(frame.target_dates)
    assert all(p.lower is p.upper is p.confidence is None for p in result)
    expected = np.asarray(predictor._fitted.forecast(1))[0]
    assert result[0].predicted_close == pytest.approx(expected)


def test_time_instrument_and_fit_guards(history, predictor):
    with pytest.raises(ValueError, match="Fit"):
        predictor.predict_series(history.inputs)
    predictor.fit(history)
    with pytest.raises(ValueError, match="Training labels"):
        predictor.predict_series(history.inputs)
    with pytest.raises(TypeError, match="never training labels"):
        predictor.predict_series(history)
    frame = inputs([history.y.iloc[-1]], start=history.target_available_at.iloc[-1])
    frame.symbol = "OTHER"
    with pytest.raises(ValueError, match="different instrument"):
        predictor.predict_series(frame)
    frame.symbol = "ENGRO"
    frame.X.iloc[0, 0] += 1
    with pytest.raises(ValueError, match="conflicts"):
        predictor.predict_series(frame)
    later = inputs([111], start=history.target_available_at.iloc[-1] + pd.Timedelta(days=2))
    with pytest.raises(ValueError, match="Replay must start"):
        predictor.predict_series(later)


def test_invalid_refit_clears_state(history, predictor):
    predictor.fit(history)
    history.y.iloc[0] += 10
    with pytest.raises(ValueError, match="contiguous"):
        predictor.fit(history)
    assert predictor._fitted is None


def test_failed_convergence_is_explicit(history, predictor):
    model_type = type(predictor._model(np.arange(20) + 100))
    with patch.object(model_type, "fit") as fit:
        fit.return_value.mle_retvals = {"converged": False}
        with pytest.raises(ValueError, match="did not converge"):
            predictor.fit(history)


def test_sarima_random_walk_matches_last_observation(history):
    predictor = SarimaPredictor(order=(0, 1, 0))
    predictor.fit(history)
    frame = inputs([history.y.iloc[-1], 120], start=history.target_available_at.iloc[-1])
    assert [p.predicted_close for p in predictor.predict_series(frame)] == pytest.approx(
        list(frame.X["price.close"])
    )
