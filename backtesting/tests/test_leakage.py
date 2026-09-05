"""Leak canaries for the walk-forward harness.

The dataset builder is already point-in-time; these assert the *fold* logic
adds no leak: no training row is scored, and every training label used by a
fold was observable strictly before that fold's first test decision.
"""

import numpy as np
import pytest
from django.conf import settings

from backtesting.tests.factories import (
    make_backtest,
    make_instrument,
    make_price_series,
    make_trading_model,
)
from backtesting.walkforward import generate_folds
from modeling.dataset import build_dataset

pytestmark = pytest.mark.django_db


@pytest.fixture
def ds_and_bt():
    inst = make_instrument("ENGRO")
    make_price_series(inst, n=420)
    model = make_trading_model([inst], estimator_key="ridge")
    bt = make_backtest(model, train_span=120, test_span=20, step=20, gap=1)
    ds = build_dataset(model, start=None, end=None, for_training=True)
    return ds, bt


def test_train_labels_precede_first_test_decision(ds_and_bt):
    ds, bt = ds_and_bt
    tz = settings.TIME_ZONE
    dates = np.array(ds.X.index.tz_convert(tz).date)
    avail = ds.available_at
    sessions = sorted(set(dates.tolist()))
    folds = generate_folds(
        sessions,
        scheme=bt.scheme,
        train_span=bt.train_span,
        test_span=bt.test_span,
        step=bt.step,
        gap=bt.gap,
    )
    assert folds

    for f in folds:
        test_mask = (dates >= f.test_start) & (dates <= f.test_end)
        if not test_mask.any():
            continue
        first_test_ts = ds.X.index[test_mask].min()
        train_mask = (
            (dates >= f.train_start) & (dates <= f.train_end) & (avail <= first_test_ts).to_numpy()
        )
        # no training decision bar falls on or after a test decision bar
        assert ds.X.index[train_mask].max() < first_test_ts
        # every retained training label was known before the test starts
        assert avail[train_mask].max() <= first_test_ts


def test_no_post_train_end_bar_enters_training_slice(ds_and_bt):
    ds, bt = ds_and_bt
    tz = settings.TIME_ZONE
    dates = np.array(ds.X.index.tz_convert(tz).date)
    sessions = sorted(set(dates.tolist()))
    folds = generate_folds(
        sessions,
        scheme=bt.scheme,
        train_span=bt.train_span,
        test_span=bt.test_span,
        step=bt.step,
        gap=bt.gap,
    )
    for f in folds:
        train_mask = (dates >= f.train_start) & (dates <= f.train_end)
        assert dates[train_mask].max() <= f.train_end
        assert f.train_end < f.test_start
