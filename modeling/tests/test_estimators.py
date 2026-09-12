import numpy as np
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
        "voting_ensemble",
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


def test_voting_ensemble_fits_and_predicts():
    rng = np.random.RandomState(0)
    X = rng.normal(size=(60, 3))
    y = X[:, 0] * 2.0 - X[:, 1] + rng.normal(scale=0.01, size=60)

    est = get_estimator("voting_ensemble").build(estimators="ridge,hist_gbr")
    est.fit(X, y)
    preds = est.predict(X)
    assert preds.shape == (60,)
    # Averaging two reasonable regressors on an easy, mostly-linear signal
    # should track y far better than a coin flip.
    assert np.corrcoef(preds, y)[0, 1] > 0.5


def test_voting_ensemble_rejects_single_estimator():
    with pytest.raises(ValueError):
        get_estimator("voting_ensemble").build(estimators="ridge")


def test_voting_ensemble_rejects_self_reference():
    with pytest.raises(ValueError):
        get_estimator("voting_ensemble").build(estimators="ridge,voting_ensemble")


def test_voting_ensemble_rejects_baseline_sub_estimator():
    with pytest.raises(ValueError):
        get_estimator("voting_ensemble").build(estimators="ridge,naive_last")


def test_voting_ensemble_rejects_classifier_sub_estimator():
    with pytest.raises(ValueError):
        get_estimator("voting_ensemble").build(estimators="ridge,logistic")
