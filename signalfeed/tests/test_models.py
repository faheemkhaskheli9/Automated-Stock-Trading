from datetime import date

import pytest
from django.core.exceptions import ValidationError

from modeling.models import TradingModel
from signalfeed.models import WatchItem
from signalfeed.tests.factories import make_instrument, make_watch_item, make_weekly_model

pytestmark = pytest.mark.django_db


def test_watchitem_accepts_weekday_anchored_model():
    inst = make_instrument("ENGRO")
    model = make_weekly_model([inst], train=False)
    item = make_watch_item(inst, model)
    item.full_clean()  # must not raise


def test_watchitem_rejects_unsupported_target():
    inst = make_instrument("HBL")
    model = TradingModel.objects.create(
        name="multistep",
        estimator_key="ridge",
        feature_spec=[{"kind": "ohlc", "fields": ["close"], "lags": [0, 1]}],
        target_spec={"type": "multistep", "steps": 3},
    )
    model.instruments.set([inst])
    item = WatchItem(instrument=inst, trading_model=model)
    with pytest.raises(ValidationError) as exc:
        item.full_clean()
    assert "trading_model" in exc.value.message_dict


def test_watchitem_rejects_out_of_range_accuracy():
    inst = make_instrument("LUCK")
    model = make_weekly_model([inst], train=False)
    item = WatchItem(instrument=inst, trading_model=model, min_directional_accuracy=1.5)
    with pytest.raises(ValidationError):
        item.full_clean()


def test_watchitem_unique_per_model():
    inst = make_instrument("OGDC")
    model = make_weekly_model([inst], train=False)
    make_watch_item(inst, model)
    with pytest.raises(Exception):
        make_watch_item(inst, model)


def test_weekly_signal_str(settings):
    from signalfeed.models import WeeklySignal

    inst = make_instrument("MCB")
    sig = WeeklySignal(
        instrument=inst,
        as_of=date(2026, 2, 2),
        target_date=date(2026, 2, 6),
        direction=WeeklySignal.Direction.UP,
    )
    assert "MCB" in str(sig) and "2026-02-06" in str(sig)
