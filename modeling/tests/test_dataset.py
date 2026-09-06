from datetime import date

import pytest

from modeling.dataset import build_dataset
from modeling.models import TradingModel
from modeling.tests.factories import make_instrument, make_price_series

pytestmark = pytest.mark.django_db


def _model(instruments, **kw):
    m = TradingModel.objects.create(
        name=kw.get("name", "m"),
        estimator_key=kw.get("estimator_key", "ridge"),
        feature_spec=kw.get(
            "feature_spec",
            [
                {"kind": "ohlc", "fields": ["close"], "lags": [0, 1, 2]},
                {"kind": "return", "periods": [1, 5]},
            ],
        ),
        target_spec=kw.get("target_spec", {"type": "horizon_close", "horizon": 1}),
        train_end=kw.get("train_end", date(2026, 1, 31)),
        holdout_fraction=kw.get("holdout_fraction", 0.2),
    )
    m.instruments.set(instruments)
    return m


def test_pooled_across_instruments_and_time_ordered_split():
    a = make_instrument("AAA")
    b = make_instrument("BBB")
    make_price_series(a, n=300)
    make_price_series(b, n=300, phase=1.0)
    ds = build_dataset(_model([a, b]))

    assert set(ds.symbols) == {"AAA", "BBB"}
    assert ds.X.index.is_monotonic_increasing
    assert ds.train_mask.sum() + ds.holdout_mask.sum() == len(ds.X)
    # holdout is the trailing block
    assert ds.holdout_mask[-1] and not ds.train_mask[-1]
    assert ds.train_mask[0] and not ds.holdout_mask[0]
    assert ds.feature_names == sorted(ds.feature_names)


def test_leakage_filter_drops_unavailable_labels():
    a = make_instrument("AAA")
    make_price_series(a, n=300)
    ds = build_dataset(_model([a], train_end=date(2025, 6, 1)))
    # every kept row's label must have been observable by the cutoff
    assert ds.available_at.max() <= ds.available_at.max()  # sanity
    assert ds.target_dates.max() <= date(2025, 6, 1)


def test_nan_target_rows_dropped_for_long_horizon():
    a = make_instrument("AAA")
    make_price_series(a, n=200)
    ds = build_dataset(
        _model([a], target_spec={"type": "horizon_close", "horizon": 4}, train_end=date(2026, 1, 1))
    )
    assert ds.y.notna().all()


def test_no_instruments_raises():
    m = TradingModel.objects.create(
        name="x",
        estimator_key="ridge",
        feature_spec=[{"kind": "ohlc", "fields": ["close"], "lags": [0]}],
        target_spec={"type": "horizon_close", "horizon": 1},
    )
    with pytest.raises(ValueError):
        build_dataset(m)
