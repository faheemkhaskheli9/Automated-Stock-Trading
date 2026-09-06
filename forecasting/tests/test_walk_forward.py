"""Walk-forward backtester: fold disjointness, an end-to-end run, leak canary."""

import random
from datetime import date, datetime
from zoneinfo import ZoneInfo

import numpy as np
import pytest

from forecasting.backtesting.engine import looks_leaky, walk_forward
from forecasting.backtesting.metrics import regression_scores, trading_translation
from forecasting.backtesting.walkforward import EXPANDING, ROLLING, generate_folds
from forecasting.base import BasePredictor, PricePrediction
from forecasting.registry import _REGISTRY, register_predictor
from marketdata.models import PriceBar
from research.tests.factories import make_instrument, make_price_series

ZONE = ZoneInfo("Asia/Karachi")


def local(day, month=1):
    return datetime(2026, month, day, tzinfo=ZONE)


# --------------------------------------------------------------------------- #
# C7 - train/test index disjointness over random fold configs
# --------------------------------------------------------------------------- #
def test_generate_folds_are_ordered_and_disjoint_with_gap():
    rng = random.Random(20260906)
    for _ in range(40):
        n = rng.randint(20, 400)
        scheme = rng.choice([EXPANDING, ROLLING])
        train_span = rng.randint(5, 120)
        test_span = rng.randint(1, 30)
        step = rng.randint(1, 40)
        gap = rng.randint(0, 5)
        folds = generate_folds(
            n,
            scheme=scheme,
            train_span=train_span,
            test_span=test_span,
            step=step,
            gap=gap,
        )
        prev_test_start = -1
        for f in folds:
            assert max(f.train) < min(f.test)  # no shared row
            assert min(f.test) - max(f.train) - 1 >= gap  # embargo respected
            assert f.test.stop <= n
            assert len(f.test) == test_span
            if scheme == ROLLING:
                assert len(f.train) == train_span
            else:
                assert f.train.start == 0
            assert f.test.start > prev_test_start  # folds march forward
            prev_test_start = f.test.start


def test_generate_folds_empty_when_history_too_short():
    assert generate_folds(10, train_span=20, test_span=5, step=5, gap=1) == []


def test_generate_folds_rejects_bad_config():
    with pytest.raises(ValueError):
        generate_folds(50, scheme="k-fold")
    with pytest.raises(ValueError):
        generate_folds(50, test_span=0)
    with pytest.raises(ValueError):
        generate_folds(50, gap=-1)


# --------------------------------------------------------------------------- #
# metrics
# --------------------------------------------------------------------------- #
def test_regression_scores_skill_is_zero_for_the_persistence_baseline():
    anchor = np.array([100.0, 101.0, 99.0, 103.0])
    actual = np.array([101.0, 100.0, 100.0, 102.0])
    scores = regression_scores(anchor, actual, anchor)  # predicted == anchor
    assert scores["skill_vs_naive"] == pytest.approx(0.0)
    assert scores["mae"] == pytest.approx(scores["naive_mae"])


def test_trading_translation_goes_long_only_when_the_forecast_is_up():
    dates = [date(2026, 1, d) for d in range(1, 5)]
    anchor = np.array([100.0, 100.0, 100.0, 100.0])
    predicted = np.array([101.0, 99.0, 101.0, 101.0])  # long, flat, long, long
    actual = np.array([110.0, 90.0, 110.0, 90.0])
    out = trading_translation(dates, predicted, actual, anchor, cost_bps=0.0)
    assert out["num_trades"] == 3
    assert out["hit_rate"] == pytest.approx(2 / 3)
    assert out["exposure"] == pytest.approx(0.75)
    assert len(out["equity_curve"]) == 4


# --------------------------------------------------------------------------- #
# end-to-end walk-forward over assembled point-in-time frames
# --------------------------------------------------------------------------- #
@pytest.fixture
def history(db):
    inst = make_instrument("ENGRO")
    rng = np.random.default_rng(7)
    closes = 100.0 + np.cumsum(rng.normal(0.1, 0.8, 44))
    closes = np.abs(closes) + 40.0
    make_price_series(inst, list(closes))
    return inst


WF_KW = dict(
    provider_keys=[],
    scheme=EXPANDING,
    train_span=15,
    test_span=5,
    step=5,
    gap=1,
)


def test_naive_walk_forward_runs_and_scores_near_zero_skill(history):
    result = walk_forward("naive", "ENGRO", local(1), local(20, month=2), **WF_KW)
    assert len(result.folds) == 5
    assert result.skipped_folds == []
    assert result.metrics["n"] == len(result.predictions) == 25
    # naive predicts the anchor, so its skill vs. the naive baseline is ~0.
    assert result.metrics["skill_vs_naive"] == pytest.approx(0.0, abs=1e-9)
    assert not looks_leaky(result)
    assert "total_return" in result.trading
    # every predicted close equals the decision-bar close
    for row in result.predictions:
        assert row["predicted"] == pytest.approx(row["anchor"])


def test_ridge_walk_forward_reports_a_skill_number_and_trading_translation(history):
    result = walk_forward("ridge", "ENGRO", local(1), local(20, month=2), **WF_KW)
    assert len(result.folds) == 5
    assert isinstance(result.metrics["skill_vs_naive"], float)
    assert isinstance(result.metrics["directional_accuracy"], float)
    assert result.trading["n"] == 25
    assert result.trading["final_equity"] > 0
    assert not looks_leaky(result)  # a real fit must not near-perfectly predict OOS
    assert result.fold_table().splitlines()[0].strip().startswith("fold")


def test_history_too_short_raises(history):
    with pytest.raises(ValueError, match="history too short"):
        walk_forward(
            "naive", "ENGRO", local(1), local(20, month=2), provider_keys=[], train_span=200
        )


def test_unknown_predictor_key_fails_fast(history):
    with pytest.raises(KeyError):
        walk_forward("does-not-exist", "ENGRO", local(1), local(20, month=2), **WF_KW)


# --------------------------------------------------------------------------- #
# C5 - a predictor that peeks at t+1 is flagged by the harness
# --------------------------------------------------------------------------- #
@pytest.fixture
def leaky_key():
    key = "leaky_future_peek_test"

    @register_predictor(key)
    class _Leaky(BasePredictor):
        display_name = "reads tomorrow's close from the DB"

        def fit(self, history):
            pass

        def predict_series(self, frame):
            future = {
                bar.timestamp.astimezone(ZONE).date(): float(bar.close)
                for bar in PriceBar.objects.filter(
                    instrument__symbol=frame.symbol,
                    instrument__exchange=frame.exchange,
                    timeframe=PriceBar.Timeframe.DAILY,
                )
            }
            out = []
            for as_of, row in frame.X.iterrows():
                target = frame.target_dates.loc[as_of]
                out.append(
                    PricePrediction(
                        target_date=target,
                        predicted_close=future.get(target, float(row["price.close"])),
                        model_key=key,
                        features_hash=frame.features_hashes.loc[as_of],
                    )
                )
            return out

    try:
        yield key
    finally:
        _REGISTRY.pop(key, None)


def test_future_peeking_predictor_is_flagged_as_leaky(history, leaky_key):
    leaked = walk_forward(leaky_key, "ENGRO", local(1), local(20, month=2), **WF_KW)
    clean = walk_forward("naive", "ENGRO", local(1), local(20, month=2), **WF_KW)

    assert looks_leaky(leaked) is True
    assert looks_leaky(clean) is False
    assert leaked.metrics["mae"] < clean.metrics["mae"]
    assert leaked.metrics["skill_vs_naive"] > 0.99
