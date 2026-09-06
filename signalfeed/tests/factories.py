from datetime import date

from modeling.models import TradingModel
from modeling.services import train_model
from modeling.tests.factories import make_instrument, make_price_series  # noqa: F401
from signalfeed.models import WatchItem

OHLC = {"kind": "ohlc", "fields": ["open", "high", "low", "close"], "lags": [0, 1, 2]}
RET = {"kind": "return", "periods": [1, 5]}
WEEKLY_TARGET = {"type": "weekday_anchored", "entry_weekday": 0, "exit_weekday": 4}


def make_weekly_model(
    instruments,
    *,
    estimator_key="ridge",
    target=None,
    feature_spec=None,
    train=True,
    is_active=True,
):
    model = TradingModel.objects.create(
        name=f"weekly-{estimator_key}",
        estimator_key=estimator_key,
        feature_spec=feature_spec or [OHLC, RET],
        target_spec=target or dict(WEEKLY_TARGET),
        train_end=date(2026, 1, 15),
        is_active=is_active,
    )
    model.instruments.set(instruments)
    if train:
        run = train_model(model)
        assert run.status == run.Status.SUCCESS, run.error
        model.refresh_from_db()
    return model


def make_watch_item(instrument, model, **kw):
    defaults = dict(
        instrument=instrument,
        trading_model=model,
        is_active=True,
        min_directional_accuracy=0.0,
        min_skill=0.0,
        min_expected_move_pct=0.0,
    )
    defaults.update(kw)
    return WatchItem.objects.create(**defaults)
