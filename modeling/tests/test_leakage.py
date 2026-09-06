"""Anti-leakage guarantees the dataset builder must keep."""

from datetime import date

import pandas as pd
import pytest

from modeling import features
from modeling.dataset import build_dataset
from modeling.models import TradingModel
from modeling.tests.factories import make_instrument, make_price_series, ohlcv_frame

TZ = "Asia/Karachi"


def test_future_bar_does_not_change_a_past_decision_row():
    spec = [
        {"kind": "ohlc", "fields": ["close"], "lags": [0, 1]},
        {"kind": "return", "periods": [1, 5]},
        {"kind": "technical", "names": ["rsi_14", "sma_10"]},
    ]
    df = ohlcv_frame(160)
    decision_index = df.index[80:120]
    before = features.build_feature_columns(
        spec, df, symbol="X", exchange="PSX", decision_index=decision_index
    )

    future = ohlcv_frame(40, start=pd.Timestamp("2030-01-01", tz="UTC"))
    extended = pd.concat([df, future])
    after = features.build_feature_columns(
        spec, extended, symbol="X", exchange="PSX", decision_index=decision_index
    )
    pd.testing.assert_frame_equal(before, after)


@pytest.mark.django_db
def test_training_rows_never_use_labels_unavailable_by_end():
    inst = make_instrument("AAA")
    make_price_series(inst, n=320)
    model = TradingModel.objects.create(
        name="m",
        estimator_key="ridge",
        feature_spec=[{"kind": "ohlc", "fields": ["close"], "lags": [0, 1, 2]}],
        target_spec={"type": "horizon_close", "horizon": 2},
        train_end=date(2025, 7, 1),
    )
    model.instruments.set([inst])
    ds = build_dataset(model)

    cutoff = pd.Timestamp("2025-07-02", tz=TZ)  # next local midnight after train_end
    assert ds.available_at.max() <= cutoff
    assert ds.target_dates.max() <= date(2025, 7, 1)
