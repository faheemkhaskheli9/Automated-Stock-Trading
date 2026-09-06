from datetime import date

from backtesting.models import Backtest
from modeling.models import TradingModel
from modeling.tests.factories import make_instrument, make_price_series  # noqa: F401

OHLC = {"kind": "ohlc", "fields": ["open", "high", "low", "close"], "lags": [0, 1, 2]}
RET = {"kind": "return", "periods": [1, 5]}


def make_trading_model(instruments, *, estimator_key="ridge", target=None, feature_spec=None):
    model = TradingModel.objects.create(
        name=f"{estimator_key}-bt",
        estimator_key=estimator_key,
        feature_spec=feature_spec or [OHLC, RET],
        target_spec=target or {"type": "horizon_close", "horizon": 1},
        train_end=date(2030, 1, 1),
    )
    model.instruments.set(instruments)
    return model


def make_backtest(model, **kw):
    defaults = dict(
        name="bt",
        model=model,
        scheme=Backtest.Scheme.EXPANDING,
        train_span=120,
        test_span=20,
        step=20,
        gap=1,
        initial_cash=100_000.0,
    )
    defaults.update(kw)
    return Backtest.objects.create(**defaults)
