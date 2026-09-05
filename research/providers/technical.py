"""Technical-indicator features.

Pure-pandas implementations so this has no dependency beyond what the
project already pins. If ``pandas_ta`` is installed it is NOT required -
these hand-rolled versions are the reference and are what the tests check.

`technical_features(df)` takes an OHLCV frame (ascending by date, columns
``open/high/low/close/volume``) and returns the indicator values **as of
the last row** - the caller is responsible for only passing rows dated
<= as_of.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from marketdata.models import Instrument, PriceBar

from .base import FeatureBundle, FeatureProvider, register_feature_provider

NAMESPACE = "technical"

# Enough history for the longest lookback (50) plus smoothing headroom.
MIN_BARS = 60


def _rsi(closes: pd.Series, period: int) -> pd.Series:
    delta = closes.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()

    rsi = pd.Series(index=closes.index, dtype=float)
    no_movement = (avg_gain == 0) & (avg_loss == 0)
    no_losses = (avg_loss == 0) & (avg_gain != 0)
    normal = avg_gain.notna() & ~no_movement & ~no_losses

    rsi[no_movement] = 50.0
    rsi[no_losses] = 100.0
    rs = avg_gain[normal] / avg_loss[normal]
    rsi[normal] = 100 - (100 / (1 + rs))
    return rsi


def _atr(df: pd.DataFrame, period: int) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period).mean()


def _last(series: pd.Series) -> float | None:
    if series is None or len(series) == 0:
        return None
    value = series.iloc[-1]
    if pd.isna(value):
        return None
    return float(value)


def technical_features(df: pd.DataFrame) -> dict[str, float]:
    """Indicator values as of the final row of ``df``. Skips any indicator
    that doesn't have enough history yet (rather than emitting NaN)."""
    if df.empty:
        return {}

    df = df.sort_index()
    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    volume = df["volume"].astype(float)

    out: dict[str, float | None] = {}

    for w in (10, 20, 50):
        out[f"sma_{w}"] = _last(close.rolling(w).mean())
        out[f"close_over_sma_{w}"] = (
            float(close.iloc[-1] / _last(close.rolling(w).mean()))
            if _last(close.rolling(w).mean())
            else None
        )
    for w in (12, 26):
        out[f"ema_{w}"] = _last(close.ewm(span=w, adjust=False).mean())

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    macd_signal = macd.ewm(span=9, adjust=False).mean()
    out["macd"] = _last(macd)
    out["macd_signal"] = _last(macd_signal)
    out["macd_hist"] = _last(macd - macd_signal)

    out["rsi_14"] = _last(_rsi(close, 14))

    mid = close.rolling(20).mean()
    std = close.rolling(20).std()
    upper = mid + 2 * std
    lower = mid - 2 * std
    if _last(mid) is not None and _last(std) not in (None, 0.0):
        out["bb_pct"] = float((close.iloc[-1] - lower.iloc[-1]) / (upper.iloc[-1] - lower.iloc[-1]))
        out["bb_width"] = float((upper.iloc[-1] - lower.iloc[-1]) / mid.iloc[-1])

    out["atr_14"] = _last(_atr(df, 14))

    lowest = low.rolling(14).min()
    highest = high.rolling(14).max()
    denom = highest - lowest
    stoch_k = 100 * (close - lowest) / denom.where(denom != 0)
    out["stoch_k"] = _last(stoch_k)
    out["stoch_d"] = _last(stoch_k.rolling(3).mean())

    direction = close.diff().pipe(lambda s: s.mask(s > 0, 1).mask(s < 0, -1).fillna(0))
    obv = (direction * volume).cumsum()
    if len(obv) >= 10:
        out["obv_slope_10"] = float((obv.iloc[-1] - obv.iloc[-10]) / 10.0)

    if len(close) > 10:
        out["roc_10"] = float(close.iloc[-1] / close.iloc[-11] - 1)
        out["mom_10"] = float(close.iloc[-1] - close.iloc[-11])

    returns = close.pct_change()
    out["volatility_20"] = _last(returns.rolling(20).std())
    out["return_1d"] = _last(returns)
    if len(close) > 5:
        out["return_5d"] = float(close.iloc[-1] / close.iloc[-6] - 1)

    vol_mean = volume.rolling(20).mean()
    vol_std = volume.rolling(20).std()
    if _last(vol_std) not in (None, 0.0):
        out["volume_z_20"] = float((volume.iloc[-1] - vol_mean.iloc[-1]) / vol_std.iloc[-1])

    if len(close) >= 2 and close.iloc[-2] != 0:
        out["gap_pct"] = float(df["open"].iloc[-1] / close.iloc[-2] - 1)

    return {f"{NAMESPACE}.{k}": v for k, v in out.items() if v is not None}


def load_ohlcv(symbol: str, as_of: datetime, *, exchange: str = "PSX") -> pd.DataFrame:
    """OHLCV frame for ``symbol`` with every bar dated <= ``as_of``,
    ascending, indexed by timestamp. Empty frame if the instrument or its
    history is missing."""
    try:
        instrument = Instrument.objects.get(exchange=exchange, symbol=symbol)
    except Instrument.DoesNotExist:
        return pd.DataFrame()

    rows = (
        PriceBar.objects.filter(
            instrument=instrument,
            timeframe=PriceBar.Timeframe.DAILY,
            timestamp__lte=as_of,
        )
        .order_by("timestamp")
        .values("timestamp", "open", "high", "low", "close", "volume")
    )
    df = pd.DataFrame.from_records(rows)
    if df.empty:
        return df
    return df.set_index("timestamp").astype(
        {"open": float, "high": float, "low": float, "close": float, "volume": float}
    )


@register_feature_provider("technical")
class TechnicalProvider(FeatureProvider):
    namespace = NAMESPACE
    display_name = "Technical Indicators"

    def get_features(self, symbol: str, as_of: datetime, *, exchange: str = "PSX") -> FeatureBundle:
        df = load_ohlcv(symbol, as_of, exchange=exchange)
        features = technical_features(df) if len(df) >= 2 else {}
        sources = [f"PriceBar history <= {as_of:%Y-%m-%d} ({len(df)} bars)"]
        return FeatureBundle(
            symbol=symbol, as_of=as_of, exchange=exchange, features=features, sources=sources
        )
