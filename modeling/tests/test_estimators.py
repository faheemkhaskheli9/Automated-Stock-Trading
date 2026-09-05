import pytest

from modeling.registry import catalogue, get_estimator, registered_keys


def test_expected_keys_registered():
    keys = set(registered_keys())
    assert {
        "linear",
        "ridge",
        "lasso",
        "elasticnet",
        "logistic",
        "random_forest",
        "gradient_boosting",
        "hist_gbr",
        "mlp",
        "naive_last",
        "drift",
        "seasonal_naive",
        "lstm",
    } <= keys


@pytest.mark.parametrize("key", [k for k in registered_keys() if k != "lstm"])
def test_available_estimator_builds(key):
    spec = get_estimator(key)
    assert spec.available
    est = spec.build()
    assert hasattr(est, "fit") and hasattr(est, "predict")


def test_lstm_unavailable_without_torch():
    spec = get_estimator("lstm")
    assert spec.available is False
    with pytest.raises(RuntimeError):
        spec.build()


def test_coerce_params_rejects_unknown():
    with pytest.raises(ValueError):
        get_estimator("ridge").coerce_params({"nope": 1})


def test_coerce_params_types():
    assert get_estimator("ridge").coerce_params({"alpha": "0.5"}) == {"alpha": 0.5}


def test_baseline_anchor_feature():
    assert get_estimator("naive_last").anchor_feature() == "ohlc.close_lag_0"
    assert get_estimator("seasonal_naive").anchor_feature({"season": 7}) == "ohlc.close_lag_7"
    assert get_estimator("ridge").anchor_feature() is None


def test_catalogue_shape():
    rows = {r["key"]: r for r in catalogue()}
    assert rows["ridge"]["task"] == "regression"
    assert rows["logistic"]["task"] == "classification"
    assert rows["lstm"]["available"] is False
