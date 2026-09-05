from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from forecasting.base import PricePrediction
from forecasting.features import assemble_prediction_frame, assemble_training_frame
from forecasting.naive import DriftPredictor, NaiveClosePredictor
from forecasting.registry import get_predictor_class, register_predictor, registered_keys
from marketdata.models import PriceBar
from research.models import CompanyFundamental, NewsItem
from research.providers.base import FeatureBundle
from research.tests.factories import make_instrument, make_price_series

ZONE = ZoneInfo("Asia/Karachi")


def local(day):
    return datetime(2026, 1, day, tzinfo=ZONE)


def training(end=5, start=2, **kwargs):
    return assemble_training_frame("ENGRO", local(start), local(end), **kwargs)


@pytest.fixture
def prices(db):
    instrument = make_instrument()
    make_price_series(instrument, [100, 102, 106, 108], start=local(1))
    return instrument


def test_registered_at_django_startup():
    assert {"naive", "drift"} <= set(registered_keys())
    assert get_predictor_class("naive") is NaiveClosePredictor
    assert register_predictor("naive")(NaiveClosePredictor) is NaiveClosePredictor
    with pytest.raises(ValueError, match="already registered"):
        register_predictor("naive")(DriftPredictor)
    with pytest.raises(KeyError, match="Known keys"):
        get_predictor_class("missing")
    with pytest.raises(ValueError, match="nonempty"):
        register_predictor("")


def test_next_observed_targets_and_lags(prices):
    frame = training(provider_keys=[])
    assert list(frame.y) == [102, 106, 108]
    assert list(frame.inputs.X["price.close"]) == [100, 102, 106]
    assert list(frame.inputs.target_dates) == [date(2026, 1, n) for n in (2, 3, 4)]
    assert list(frame.target_available_at) == [local(n) for n in (3, 4, 5)]
    assert pd.isna(frame.inputs.X.iloc[0]["price.close_lag_1"])
    assert frame.inputs.X.iloc[2]["price.close_lag_1"] == 102
    assert frame.inputs.X.iloc[2]["price.return_2"] == pytest.approx(0.06)
    assert not hasattr(frame.inputs, "y")


def test_end_cutoff_never_reads_current_day_close(prices):
    # Jan 3's 106 close is stored at midnight but is not known at noon.
    noon = local(3) + timedelta(hours=12)
    frame = assemble_training_frame("ENGRO", local(2), noon, provider_keys=[])
    assert list(frame.y) == [102]
    prediction = assemble_prediction_frame(
        "ENGRO", noon, target_date=date(2026, 1, 3), provider_keys=["technical"]
    )
    assert prediction.X.iloc[0]["price.close"] == 102
    assert prediction.X.iloc[0]["technical.return_1d"] == pytest.approx(0.02)


def test_start_retains_prior_warmup_and_empty_label_window(prices):
    frame = training(start=4, provider_keys=[])
    assert len(frame.y) == 1
    assert frame.inputs.X.iloc[0]["price.close_lag_2"] == 100
    empty = training(start=5, provider_keys=[])
    assert empty.y.empty
    assert NaiveClosePredictor().predict_series(empty.inputs) == []


def test_future_bar_and_headline_cannot_change_past_features(prices):
    before = training(end=4)
    PriceBar.objects.filter(instrument=prices, timestamp=local(4)).update(
        close=999, high=1000, low=100
    )
    NewsItem.objects.create(
        symbol="ENGRO",
        headline="Future",
        url="https://example.com/future",
        url_hash="future",
        published_at=local(5),
        sentiment=1,
    )
    after = training(end=4)
    pd.testing.assert_frame_equal(before.inputs.X, after.inputs.X)
    pd.testing.assert_series_equal(before.inputs.features_hashes, after.inputs.features_hashes)
    pd.testing.assert_series_equal(before.y, after.y)


def test_changed_target_does_not_change_earlier_feature_hash(prices):
    before = training(end=3)
    PriceBar.objects.filter(instrument=prices, timestamp=local(2)).update(close=101)
    after = training(end=3)
    pd.testing.assert_frame_equal(before.inputs.X, after.inputs.X)
    pd.testing.assert_series_equal(before.inputs.features_hashes, after.inputs.features_hashes)
    assert before.y.iloc[0] == 102
    assert after.y.iloc[0] == 101


def test_news_is_evaluated_at_each_decision_time(prices):
    NewsItem.objects.create(
        symbol="ENGRO",
        headline="Known at Jan 3 decision",
        url="https://example.com/known",
        url_hash="known",
        published_at=local(2) + timedelta(hours=12),
        sentiment=0.5,
    )
    frame = training(end=4, provider_keys=["news"])
    assert list(frame.inputs.X["news.count_7d"]) == [0, 1]


def test_date_only_fundamentals_wait_until_following_day(prices):
    CompanyFundamental.objects.create(
        symbol="ENGRO", as_of_report_date=date(2026, 1, 2), ratios={"eps": 4}
    )
    frame = training(end=4, provider_keys=["fundamentals"])
    assert pd.isna(frame.inputs.X.iloc[0]["fundamentals.eps"])
    assert frame.inputs.X.iloc[1]["fundamentals.eps"] == 4


def test_nonfinite_provider_features_are_rejected(prices):
    with patch("forecasting.features.get_feature_provider") as provider:
        provider.return_value.return_value.get_features.return_value = FeatureBundle(
            "ENGRO", local(2), features={"custom.value": float("nan")}
        )
        with pytest.raises(ValueError, match="Non-finite feature"):
            training(provider_keys=["custom"])


def test_provider_cannot_advance_cutoff_or_silently_fail(prices):
    future = FeatureBundle("ENGRO", local(6), features={"custom.value": 99})
    with patch("forecasting.features.get_feature_provider") as provider:
        provider.return_value.return_value.get_features.return_value = future
        with pytest.raises(ValueError, match="point-in-time"):
            training(provider_keys=["custom"])
        provider.return_value.return_value.get_features.side_effect = RuntimeError("offline")
        with pytest.raises(RuntimeError, match="offline"):
            training(provider_keys=["custom"])


def test_exchange_isolation_and_utc_cutoff_equivalence(prices):
    other = make_instrument(exchange="OTHER")
    make_price_series(other, [1, 2, 3], start=local(1))
    frame = training(end=4, provider_keys=[])
    utc = assemble_training_frame(
        "ENGRO",
        local(2).astimezone(timezone.utc),
        local(4).astimezone(timezone.utc),
        provider_keys=[],
    )
    pd.testing.assert_frame_equal(frame.inputs.X, utc.inputs.X)
    assert list(frame.inputs.X["price.close"]) == [100, 102]


def test_targets_follow_observations_across_gap(db):
    instrument = make_instrument()
    make_price_series(instrument, [100], start=local(2))
    make_price_series(instrument, [110], start=local(5))
    frame = training(end=6, provider_keys=[])
    assert frame.inputs.target_dates.iloc[0] == date(2026, 1, 5)
    assert frame.target_available_at.iloc[0] == local(6)


def test_naive_and_drift_have_hand_computed_predictions(prices):
    train = training(end=4, provider_keys=[])
    test = training(start=4, end=5, provider_keys=[]).inputs
    naive = NaiveClosePredictor()
    naive.fit(train)
    assert naive.predict_series(test)[0].predicted_close == 106
    drift = DriftPredictor()
    drift.fit(train)  # mean((102 - 100), (106 - 102)) = 3
    result = drift.predict_series(test)
    assert len(result) == len(test.X)
    assert result[0].predicted_close == 109
    assert result[0].model_key == "drift"
    assert result[0].lower is result[0].upper is result[0].confidence is None
    assert len(result[0].features_hash) == 64
    assert drift.predict_series(test) == result


def test_drift_refuses_future_fitted_state_and_wrong_instrument(prices):
    frame = training(provider_keys=[])
    predictor = DriftPredictor()
    with pytest.raises(ValueError, match="Fit"):
        predictor.predict_series(frame.inputs)
    predictor.fit(frame)
    with pytest.raises(ValueError, match="Training labels"):
        predictor.predict_series(frame.inputs)
    future = assemble_prediction_frame(
        "ENGRO", local(5), target_date=date(2026, 1, 5), provider_keys=[]
    )
    future.symbol = "OTHER"
    with pytest.raises(ValueError, match="different instrument"):
        predictor.predict_series(future)
    with pytest.raises(TypeError, match="never training labels"):
        predictor.predict_series(frame)


def test_predict_next_requires_explicit_target_and_uses_completed_history(prices):
    result = NaiveClosePredictor().predict_next("ENGRO", local(5), target_date=date(2026, 1, 5))
    assert result.predicted_close == 108
    assert result.target_date == date(2026, 1, 5)
    with pytest.raises(ValueError, match="future session"):
        NaiveClosePredictor().predict_next("ENGRO", local(5), target_date=date(2026, 1, 4))


def test_bad_history_and_naive_datetimes_fail_clearly(prices):
    with pytest.raises(ValueError, match="timezone-aware"):
        assemble_training_frame("ENGRO", datetime(2026, 1, 1), local(5))
    with pytest.raises(ValueError, match="start"):
        training(start=5, end=2)
    with pytest.raises(ValueError, match="No completed"):
        assemble_training_frame("UNKNOWN", local(1), local(5))
    PriceBar.objects.filter(instrument=prices, timestamp=local(1)).update(is_anomaly=True)
    with pytest.raises(ValueError, match="anomalies"):
        training()


@pytest.mark.parametrize("value", [float("nan"), float("inf"), 0, -1])
def test_invalid_forecast_values_rejected(value):
    with pytest.raises(ValueError, match="finite and positive"):
        PricePrediction(date(2026, 1, 5), value, "naive", "hash")


def test_prediction_metadata_alignment_is_enforced(prices):
    frame = training(provider_keys=[])
    frame.inputs.target_dates = frame.inputs.target_dates.iloc[::-1]
    with pytest.raises(ValueError, match="align"):
        frame.inputs.__post_init__()
