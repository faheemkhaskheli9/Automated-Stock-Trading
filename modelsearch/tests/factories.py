from datetime import date

from modeling.models import TradingModel
from modeling.tests.factories import make_instrument, make_price_series
from modelsearch.models import ModelSearch

OHLC = {"kind": "ohlc", "fields": ["open", "high", "low", "close"], "lags": [0, 1, 2]}
RET = {"kind": "return", "periods": [1, 5]}
FEATURE_SPEC = [OHLC, RET]
TARGET_SPEC = {"type": "horizon_close", "horizon": 1}


def make_base_model(instruments, *, estimator_key="ridge", target_spec=None):
    model = TradingModel.objects.create(
        name="base",
        estimator_key=estimator_key,
        estimator_params={},
        feature_spec=FEATURE_SPEC,
        target_spec=target_spec or TARGET_SPEC,
        train_end=date(2026, 1, 31),
        holdout_fraction=0.2,
    )
    model.instruments.set(instruments)
    return model


def make_search(instruments, *, search_space=None, target_spec=None, base=None, **kw):
    search = ModelSearch.objects.create(
        name="sweep",
        base_model=base,
        feature_spec=FEATURE_SPEC,
        target_spec=target_spec or TARGET_SPEC,
        train_end=date(2026, 1, 31),
        holdout_fraction=0.2,
        search_space=search_space
        or {
            "estimators": ["ridge", "random_forest"],
            "param_grids": {"ridge": {"alpha": [0.1, 1.0]}},
        },
        **kw,
    )
    search.instruments.set(instruments)
    return search


__all__ = [
    "make_instrument",
    "make_price_series",
    "make_base_model",
    "make_search",
    "FEATURE_SPEC",
    "TARGET_SPEC",
]
