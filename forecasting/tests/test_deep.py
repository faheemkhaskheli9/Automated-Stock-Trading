"""Tests for the optional PyTorch LSTM predictor.

The module must import cleanly whether or not the ``torch`` extra is present.
The round-trip / leakage-guard scenarios mirror ``test_trees.py`` but only run
where torch is installed; the shared guard contract lives in
``forecasting._frame_model`` and is already covered by the linear/tree suites.
"""

from copy import deepcopy
from datetime import date, datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from forecasting import deep
from forecasting.base import PredictionFrame, TrainingFrame
from forecasting.features import assemble_prediction_frame, assemble_training_frame
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


def follow_on(history, closes, *, momentum=None):
    start = history.inputs.X.index.max() + pd.Timedelta(days=1)
    extra = {"tech.momentum": momentum if momentum is not None else [0.0] * len(closes)}
    return make_inputs(closes, extra=extra, start=start)


def test_module_imports_and_registration_tracks_torch():
    """Importing the module never fails; registration follows LSTM_AVAILABLE."""
    if deep.LSTM_AVAILABLE:
        assert "lstm" in set(registered_keys())
        assert get_predictor_class("lstm") is deep.LstmPredictor
    else:
        assert "lstm" not in set(registered_keys())
        with pytest.raises(KeyError):
            get_predictor_class("lstm")
        assert not hasattr(deep, "LstmPredictor")


@pytest.mark.skipif(not deep.LSTM_AVAILABLE, reason="requires the torch extra")
class TestWithTorch:
    @pytest.fixture
    def history(self):
        rng = np.random.default_rng(0)
        closes = 100.0 + np.cumsum(rng.normal(0.05, 0.6, 41))
        closes = np.abs(closes) + 50.0
        momentum = np.concatenate([[0.0], np.diff(closes[:-1])])
        return make_training(closes[:-1], closes[1:], extra={"tech.momentum": momentum})

    @pytest.fixture
    def predictor(self):
        return deep.LstmPredictor(lookback=4, hidden_size=8, epochs=5)

    def test_registration(self, predictor):
        assert predictor.key == "lstm"
        assert predictor.trainable is True

    def test_predict_series_round_trip(self, history, predictor):
        predictor.fit(history)
        frame = follow_on(history, [161.0, 162.5, 159.0], momentum=[1.0, 1.5, -3.5])
        result = predictor.predict_series(frame)
        assert len(result) == len(frame.X)
        assert all(p.predicted_close > 0 for p in result)
        assert [p.model_key for p in result] == ["lstm"] * 3
        assert [p.features_hash for p in result] == list(frame.features_hashes)
        assert [p.target_date for p in result] == list(frame.target_dates)
        assert all(p.lower is p.upper is p.confidence is None for p in result)
        # Deterministic, and causal: mutating the last row leaves earlier rows.
        assert predictor.predict_series(frame) == result
        mutated = deepcopy(frame)
        mutated.X.iloc[-1] = [999.0, 5.0]
        assert predictor.predict_series(mutated)[:-1] == result[:-1]

    def test_fit_input_guards(self, history, predictor):
        with pytest.raises(TypeError, match="TrainingFrame"):
            predictor.fit(history.inputs)
        short = make_training([10.0, 11.0, 12.0, 13.0], [11.0, 12.0, 13.0, 14.0])
        with pytest.raises(ValueError, match="at least"):
            predictor.fit(short)
        bad = deepcopy(history)
        bad.inputs.X.iloc[0, bad.inputs.X.columns.get_loc("price.close")] = -1.0
        with pytest.raises(ValueError, match="finite and positive"):
            predictor.fit(bad)

    def test_prediction_guards(self, history, predictor):
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

    def test_failed_refit_clears_state(self, history, predictor):
        predictor.fit(history)
        assert predictor._pipeline is not None
        broken = deepcopy(history)
        broken.inputs.X["price.close"] = np.nan
        with pytest.raises(ValueError, match="finite and positive"):
            predictor.fit(broken)
        assert predictor._pipeline is None

    def test_fit_and_predict_over_assembled_frames(self, db, predictor):
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
        assert prediction.model_key == "lstm"
        assert prediction.target_date == date(2026, 1, 9)
        assert len(prediction.features_hash) == 64
