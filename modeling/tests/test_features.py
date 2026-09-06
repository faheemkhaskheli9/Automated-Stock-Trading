import numpy as np
import pytest

from modeling import features
from modeling.tests.factories import make_instrument, make_price_series, ohlcv_frame

TZ = "Asia/Karachi"


def _cols(spec, df=None, idx_slice=slice(60, 120)):
    df = df if df is not None else ohlcv_frame(160)
    idx = df.index[idx_slice]
    return (
        features.build_feature_columns(
            spec, df, symbol="ENGRO", exchange="PSX", decision_index=idx
        ),
        df,
        idx,
    )


def test_ohlc_lags():
    cols, df, idx = _cols([{"kind": "ohlc", "fields": ["close", "open"], "lags": [0, 1, 2]}])
    assert set(cols.columns) == {
        "ohlc.close_lag_0",
        "ohlc.close_lag_1",
        "ohlc.close_lag_2",
        "ohlc.open_lag_0",
        "ohlc.open_lag_1",
        "ohlc.open_lag_2",
    }
    pos = df.index.get_loc(idx[0])
    assert cols["ohlc.close_lag_0"].iloc[0] == pytest.approx(df["close"].iloc[pos])
    assert cols["ohlc.close_lag_2"].iloc[0] == pytest.approx(df["close"].iloc[pos - 2])


def test_return_periods():
    cols, df, idx = _cols([{"kind": "return", "periods": [1, 5]}])
    pos = df.index.get_loc(idx[0])
    assert cols["return.5"].iloc[0] == pytest.approx(
        df["close"].iloc[pos] / df["close"].iloc[pos - 5] - 1
    )


def test_calendar():
    cols, df, idx = _cols([{"kind": "calendar", "features": ["weekday", "month"]}])
    assert cols["calendar.weekday"].iloc[0] == idx[0].tz_convert(TZ).weekday()


def test_technical_point_in_time():
    from research.providers.technical import technical_features

    df = ohlcv_frame(160)
    idx = df.index[100:104]
    cols = features.build_feature_columns(
        [{"kind": "technical", "names": ["rsi_14"]}],
        df,
        symbol="X",
        exchange="PSX",
        decision_index=idx,
    )
    pos = df.index.get_loc(idx[-1])
    expected = technical_features(df.iloc[: pos + 1])["technical.rsi_14"]
    assert cols["technical.rsi_14"].iloc[-1] == pytest.approx(expected)


def test_strategy_signal_by_key_maps_to_ternary():
    cols, df, idx = _cols(
        [{"kind": "strategy_signal", "strategy_key": "rsi", "params": {"period": 14}}]
    )
    vals = set(np.unique(cols["signal.rsi"].dropna()))
    assert vals <= {-1.0, 0.0, 1.0}


def test_duplicate_columns_rejected():
    with pytest.raises(ValueError):
        _cols(
            [
                {"kind": "ohlc", "fields": ["close"], "lags": [0]},
                {"kind": "ohlc", "fields": ["close"], "lags": [0]},
            ]
        )


def test_validate_spec_errors():
    with pytest.raises(ValueError):
        features.validate_spec([])
    with pytest.raises(ValueError):
        features.validate_spec([{"kind": "nope"}])
    with pytest.raises(ValueError):
        features.validate_spec([{"kind": "ohlc", "fields": ["xyz"], "lags": [0]}])
    with pytest.raises(ValueError):
        features.validate_spec([{"kind": "strategy_signal"}])  # needs id XOR key


@pytest.mark.django_db
def test_strategy_signal_by_id_and_manual(monkeypatch):
    from strategies.models import ManualSignal, Strategy

    inst = make_instrument("ENGRO")
    make_price_series(inst, n=120)
    strat = Strategy.objects.create(name="rsi14", key="rsi", params={"period": 14})
    ManualSignal.objects.create(
        instrument=inst, date=inst.price_bars.first().timestamp.date(), action="buy"
    )

    import pandas as pd

    from modeling import features as fmod
    from modeling.dataset import build_dataset  # noqa: F401  (import sanity)

    rows = list(
        inst.price_bars.order_by("timestamp").values(
            "timestamp", "open", "high", "low", "close", "volume"
        )
    )
    df = pd.DataFrame(rows, index=pd.DatetimeIndex([r["timestamp"] for r in rows]).tz_convert(TZ))
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = df[c].astype(float)
    idx = df.index[80:90]
    cols = fmod.build_feature_columns(
        [{"kind": "strategy_signal", "strategy_id": strat.pk}, {"kind": "manual_signal"}],
        df,
        symbol="ENGRO",
        exchange="PSX",
        decision_index=idx,
    )
    assert "signal.rsi" in cols.columns
    assert "signal.manual" in cols.columns
