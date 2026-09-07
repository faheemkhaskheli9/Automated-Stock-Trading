import pytest

from modelsearch import spaces

pytestmark = pytest.mark.django_db  # spaces.validate touches the estimator registry


def test_expand_grid_counts():
    space = {
        "estimators": ["ridge", "random_forest"],
        "param_grids": {
            "ridge": {"alpha": [0.1, 1.0, 10.0]},
            "random_forest": {"n_estimators": [100, 300], "max_depth": [3, 5]},
        },
    }
    cands = spaces.expand(space, mode="grid", max_candidates=99)
    # 3 ridge + (2 x 2) random_forest
    assert len(cands) == 3 + 4
    assert ("ridge", {"alpha": 0.1}) in cands


def test_estimator_without_grid_is_one_default_candidate():
    cands = spaces.expand({"estimators": ["ridge"], "param_grids": {}}, max_candidates=10)
    assert cands == [("ridge", {})]


def test_expand_dedupes_identical_combos():
    space = {"estimators": ["ridge"], "param_grids": {"ridge": {"alpha": [1.0, 1.0]}}}
    assert spaces.expand(space) == [("ridge", {"alpha": 1.0})]


def test_random_mode_respects_cap_and_is_seed_deterministic():
    space = {"estimators": ["ridge"], "param_grids": {"ridge": {"alpha": [0.1, 1, 2, 3, 4, 5]}}}
    a = spaces.expand(space, mode="random", max_candidates=3, seed=7)
    b = spaces.expand(space, mode="random", max_candidates=3, seed=7)
    c = spaces.expand(space, mode="random", max_candidates=3, seed=8)
    assert len(a) == 3 and a == b and a != c


def test_params_hash_is_order_independent():
    assert spaces.params_hash("x", {"a": 1, "b": 2}) == spaces.params_hash("x", {"b": 2, "a": 1})


def test_validate_rejects_unknown_estimator():
    with pytest.raises(ValueError, match="No estimator registered"):
        spaces.validate({"estimators": ["nope"]}, task="regression")


def test_validate_rejects_task_mismatch():
    with pytest.raises(ValueError, match="classification model"):
        spaces.validate({"estimators": ["logistic"]}, task="regression")


def test_validate_rejects_unknown_param_name():
    with pytest.raises(ValueError, match="unknown params"):
        spaces.validate(
            {"estimators": ["ridge"], "param_grids": {"ridge": {"bogus": [1]}}},
            task="regression",
        )


def test_validate_rejects_uncoercible_value():
    with pytest.raises(ValueError, match="must be float"):
        spaces.validate(
            {"estimators": ["ridge"], "param_grids": {"ridge": {"alpha": ["abc"]}}},
            task="regression",
        )


def test_validate_rejects_grid_key_not_in_estimators():
    with pytest.raises(ValueError, match="not in estimators"):
        spaces.validate(
            {"estimators": ["ridge"], "param_grids": {"random_forest": {"n_estimators": [10]}}},
            task="regression",
        )


def test_scalar_score_negates_error_metrics():
    assert spaces.scalar_score({"mae": 2.0}, "neg_mae") == -2.0
    assert spaces.scalar_score({"r2": 0.5}, "r2") == 0.5
