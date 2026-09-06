"""B16 - one round-trip contract every registered predictor must satisfy.

The per-family suites (``test_linear``/``test_stats``/``test_trees``/``test_deep``
and the baselines in ``test_forecasting``) already pin each predictor's own
behaviour. This module is the registry-wide guard: whatever is registered at
Django startup must ``fit`` on an assembled training slice and then return
exactly one aligned, positive forecast per input row - so a newly registered
predictor that forgets the contract fails here even if it ships without its own
test.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pytest

from forecasting.base import PredictionFrame
from forecasting.features import assemble_training_frame
from forecasting.registry import get_predictor_class, registered_keys
from research.tests.factories import make_instrument, make_price_series

ZONE = ZoneInfo("Asia/Karachi")
BASE = datetime(2026, 1, 1, tzinfo=ZONE)

# Baselines that must always be present regardless of optional extras (torch).
REQUIRED_KEYS = {"naive", "drift", "sarima", "ets", "ridge", "elasticnet", "gradient_boosting"}

# Fast-but-valid overrides so every model fits on a short daily fixture.
FIT_PARAMS = {
    "sarima": {"order": (1, 1, 0)},
    "gradient_boosting": {"max_iter": 20},
    "lstm": {"lookback": 4, "hidden_size": 8, "epochs": 5},
}


def build_predictor(key):
    return get_predictor_class(key)(**FIT_PARAMS.get(key, {}))


@pytest.fixture
def frames(db):
    """A contiguous daily history split into a training slice and a follow-on
    prediction frame that begins exactly at ``fitted_through``.

    Both frames come from ``assemble_training_frame(provider_keys=[])`` so the
    feature schema matches for the frame-model predictors, and the first
    prediction row reproduces the final training label for the statistical
    predictors' prefix replay.
    """
    instrument = make_instrument()
    steps = np.arange(46)
    closes = [round(100.0 + 0.2 * i + np.sin(i), 3) for i in steps]
    make_price_series(instrument, closes, start=BASE)

    full = assemble_training_frame("ENGRO", BASE, BASE + timedelta(days=60), provider_keys=[])
    train = assemble_training_frame("ENGRO", BASE, BASE + timedelta(days=41), provider_keys=[])
    boundary = train.target_available_at.max()
    mask = full.inputs.X.index >= boundary
    prediction = PredictionFrame(
        full.inputs.symbol,
        full.inputs.exchange,
        full.inputs.X[mask],
        full.inputs.target_dates[mask],
        full.inputs.features_hashes[mask],
    )
    assert len(prediction.X) >= 3
    assert prediction.X.index.min() == boundary
    return train, prediction


def empty_like(frame):
    return PredictionFrame(
        frame.symbol,
        frame.exchange,
        frame.X.iloc[:0],
        frame.target_dates.iloc[:0],
        frame.features_hashes.iloc[:0],
    )


def test_required_predictors_are_registered():
    assert REQUIRED_KEYS <= set(registered_keys())


@pytest.mark.parametrize("key", registered_keys())
def test_registered_predictor_round_trips(frames, key):
    train, prediction = frames
    predictor = build_predictor(key)
    predictor.fit(train)

    result = predictor.predict_series(prediction)

    assert len(result) == len(prediction.X)
    assert all(p.predicted_close > 0 for p in result)
    assert [p.model_key for p in result] == [key] * len(prediction.X)
    assert [p.features_hash for p in result] == list(prediction.features_hashes)
    assert [p.target_date for p in result] == list(prediction.target_dates)
    assert all(len(p.features_hash) == 64 for p in result)
    # An empty frame is a no-op, and prediction is a pure function of inputs.
    assert predictor.predict_series(empty_like(prediction)) == []
    assert predictor.predict_series(prediction) == result
