from datetime import date

import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import LinearRegression
from sklearn.multioutput import MultiOutputRegressor
from sklearn.pipeline import Pipeline
from sklearn.tree import DecisionTreeRegressor

from modeling.explain import explain_prediction, explanation_text
from modeling.models import TradingModel
from modeling.services import predict, train_model
from modeling.tests.factories import make_instrument, make_price_series

pytestmark = pytest.mark.django_db

FEATURES = ["a", "b", "c"]


def _linear_pipeline():
    model = LinearRegression()
    model.coef_ = np.array([1.0, -5.0, 0.1])
    model.intercept_ = 0.0
    pipeline = Pipeline([("model", model)])
    return pipeline


def test_linear_attribution_ranks_by_absolute_contribution():
    pipeline = _linear_pipeline()
    row = pd.DataFrame([[2.0, 1.0, 100.0]], columns=FEATURES)
    explanation = explain_prediction(pipeline, FEATURES, row)
    assert explanation["method"] == "linear_coefficients"
    top = explanation["top_features"]
    # b: -5*1=-5, a: 1*2=2, c: 0.1*100=10 -> ranked |contribution| desc: c, b, a
    assert [f["feature"] for f in top] == ["c", "b", "a"]
    assert top[0]["direction"] == "+"
    assert top[1]["direction"] == "-"


def test_tree_attribution_uses_feature_importances():
    # "c" alone determines y; "a"/"b" are noise -> the fitted tree should
    # give "c" all (or nearly all) of the importance.
    rng = np.random.default_rng(0)
    X = pd.DataFrame(
        {"a": rng.normal(size=200), "b": rng.normal(size=200), "c": rng.normal(size=200)}
    )
    y = (X["c"] > 0).astype(float)
    tree = DecisionTreeRegressor(max_depth=2, random_state=0).fit(X, y)
    pipeline = Pipeline([("model", tree)])

    row = pd.DataFrame([[2.0, 1.0, 100.0]], columns=FEATURES)
    explanation = explain_prediction(pipeline, FEATURES, row)
    assert explanation["method"] == "feature_importance"
    assert explanation["top_features"][0]["feature"] == "c"
    assert all(f["direction"] is None for f in explanation["top_features"])


def test_multioutput_estimator_has_no_attribution():
    pipeline = Pipeline([("model", MultiOutputRegressor(LinearRegression()))])
    row = pd.DataFrame([[1.0, 2.0, 3.0]], columns=FEATURES)
    assert explain_prediction(pipeline, FEATURES, row) is None


def test_mismatched_feature_count_returns_none():
    pipeline = _linear_pipeline()
    row = pd.DataFrame([[2.0, 1.0]], columns=["a", "b"])
    assert explain_prediction(pipeline, ["a", "b"], row) is None


def test_explanation_text_formats_and_degrades():
    assert explanation_text(None) == "no attribution available for this model"
    assert explanation_text({"top_features": []}) == "no attribution available for this model"
    text = explanation_text(
        {
            "top_features": [
                {"feature": "return.5", "value": 0.021, "weight": 0.018, "direction": "+"},
            ]
        }
    )
    assert "return.5" in text and "+" in text


OHLC = {"kind": "ohlc", "fields": ["open", "high", "low", "close"], "lags": [0, 1, 2]}


def test_predict_persists_a_linear_explanation():
    inst = make_instrument("ENGRO")
    make_price_series(inst, n=420)
    model = TradingModel.objects.create(
        name="close+1",
        estimator_key="ridge",
        feature_spec=[OHLC, {"kind": "return", "periods": [1, 5]}],
        target_spec={"type": "horizon_close", "horizon": 1},
        train_end=date(2026, 1, 15),
    )
    model.instruments.set([inst])
    assert train_model(model).status == "success"
    model.refresh_from_db()

    pred = predict(model, inst, date(2026, 2, 1), target_date=date(2026, 2, 2))
    assert pred.explanation is not None
    assert pred.explanation["method"] == "linear_coefficients"
    assert pred.explanation["top_features"]
    assert "no attribution" not in explanation_text(pred.explanation)
