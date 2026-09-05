"""The daily feature/label boundary.

Only fully elapsed local days are used: a date-labelled daily bar is known
at the NEXT local midnight, even if its stored timestamp is midnight. This
deliberately sacrifices same-evening forecasts until ingestion has explicit
session-close/publication timestamps. Exchange timezone is an explicit input.

Labels are next OBSERVED bars, not proof of consecutive exchange sessions.
Missing/suspended sessions need a verified calendar in the later backtester.
Research features are rebuilt at each decision time (no latest snapshot or
provider-set-ambiguous cache). Technical features use only the eligible prefix.
Raw history is not corporate-action adjusted or revision-versioned yet.
"""

import hashlib
import json
from datetime import date, datetime, time, timedelta
from math import isfinite
from zoneinfo import ZoneInfo

import pandas as pd

from marketdata.models import PriceBar
from research.providers.base import get_feature_provider
from research.providers.technical import technical_features

from .base import PredictionFrame, TrainingFrame

DEFAULT_PROVIDERS = ("technical", "news", "fundamentals", "social")


def _aware(value, name):
    stamp = pd.Timestamp(value)
    if pd.isna(stamp) or stamp.tzinfo is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")
    return stamp


def _history(symbol, as_of, exchange, exchange_timezone):
    zone = ZoneInfo(exchange_timezone)
    cutoff = _aware(as_of, "as_of").tz_convert(zone)
    rows = list(
        PriceBar.objects.filter(
            instrument__symbol=symbol,
            instrument__exchange=exchange,
            timeframe=PriceBar.Timeframe.DAILY,
            timestamp__lt=cutoff.normalize(),
        )
        .order_by("timestamp")
        .values("timestamp", "open", "high", "low", "close", "volume", "is_anomaly")
    )
    if not rows:
        raise ValueError(f"No completed daily history for {symbol} ({exchange})")
    days = [row["timestamp"].astimezone(zone).date() for row in rows]
    if len(days) != len(set(days)):
        raise ValueError("Multiple daily bars for the same local session date")
    if any(row["is_anomaly"] for row in rows):
        raise ValueError("History contains flagged anomalies; resolve them before forecasting")
    available = pd.DatetimeIndex(
        [datetime.combine(day + timedelta(days=1), time.min, zone) for day in days],
        name="as_of",
    )
    df = pd.DataFrame(rows, index=available)[["open", "high", "low", "close", "volume"]].astype(
        float
    )
    for column in df.columns:
        if not df[column].map(isfinite).all():
            raise ValueError("History contains non-finite values")
    if (df[["open", "high", "low", "close"]] <= 0).any().any() or (df.volume < 0).any():
        raise ValueError("History contains invalid prices or volume")
    if (
        (df.high < df[["open", "close", "low"]].max(axis=1))
        | (df.low > df[["open", "close"]].min(axis=1))
    ).any():
        raise ValueError("History contains inconsistent OHLC values")
    return df, days


def _features(symbol, exchange, prefix, as_of, provider_keys):
    close = prefix.close
    values = {"price.close": float(close.iloc[-1]), "price.volume": float(prefix.volume.iloc[-1])}
    for lag in (1, 2, 5):
        if len(close) > lag:
            values[f"price.close_lag_{lag}"] = float(close.iloc[-1 - lag])
            values[f"price.return_{lag}"] = float(close.iloc[-1] / close.iloc[-1 - lag] - 1)
    for key in provider_keys:
        if key == "technical":
            extra = technical_features(prefix)
        else:
            # Strict here: silently dropping a failed provider changes the
            # training schema and can conceal invalid point-in-time inputs.
            bundle = get_feature_provider(key)().get_features(symbol, as_of, exchange=exchange)
            if bundle.symbol != symbol or bundle.exchange != exchange or bundle.as_of != as_of:
                raise ValueError(f"Provider {key!r} returned mismatched point-in-time metadata")
            extra = bundle.features
        if values.keys() & extra.keys():
            raise ValueError("Feature key collision")
        for name, value in extra.items():
            if not isfinite(value):
                raise ValueError(f"Non-finite feature {name!r}")
            values[name] = float(value)
    payload = {
        "symbol": symbol,
        "exchange": exchange,
        "as_of": as_of.isoformat(),
        "features": values,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    return values, digest


def assemble_training_frame(
    symbol: str,
    start: datetime,
    end: datetime,
    *,
    exchange="PSX",
    exchange_timezone="Asia/Karachi",
    provider_keys=DEFAULT_PROVIDERS,
) -> TrainingFrame:
    """Include feature rows >= start and labels available <= end.

    Keep earlier history for lag/indicator warmup. The final unlabelled bar
    never becomes a training row. Missing indicator warmups remain NaN;
    there is no forward/backward fill or full-series normalization.
    """
    start, end = _aware(start, "start"), _aware(end, "end")
    if start > end:
        raise ValueError("start must not be after end")
    df, days = _history(symbol, end, exchange, exchange_timezone)
    records, hashes, indexes, dates, labels, known = [], [], [], [], [], []
    for i in range(len(df) - 1):
        as_of = df.index[i]
        if as_of < start:
            continue
        values, digest = _features(symbol, exchange, df.iloc[: i + 1], as_of, provider_keys)
        records.append(values)
        hashes.append(digest)
        indexes.append(as_of)
        dates.append(days[i + 1])
        labels.append(float(df.close.iloc[i + 1]))
        known.append(df.index[i + 1])
    index = pd.DatetimeIndex(indexes, tz=exchange_timezone, name="as_of")
    inputs = PredictionFrame(
        symbol,
        exchange,
        pd.DataFrame(records, index=index, dtype=float).sort_index(axis=1),
        pd.Series(dates, index=index, dtype=object),
        pd.Series(hashes, index=index, dtype=object),
    )
    return TrainingFrame(
        inputs,
        pd.Series(labels, index=index, dtype=float),
        pd.Series(known, index=index, dtype=f"datetime64[ns, {exchange_timezone}]"),
    )


def assemble_prediction_frame(
    symbol,
    as_of,
    *,
    target_date: date,
    exchange="PSX",
    exchange_timezone="Asia/Karachi",
    provider_keys=DEFAULT_PROVIDERS,
) -> PredictionFrame:
    """Build one input row without reading future prices or guessing holidays."""
    as_of = _aware(as_of, "as_of").tz_convert(exchange_timezone)
    df, days = _history(symbol, as_of, exchange, exchange_timezone)
    if not isinstance(target_date, date) or isinstance(target_date, datetime):
        raise ValueError("target_date must be a date")
    if target_date <= days[-1] or target_date < as_of.date():
        raise ValueError("target_date must be a future session relative to available history")
    values, digest = _features(symbol, exchange, df, as_of, provider_keys)
    index = pd.DatetimeIndex([as_of], name="as_of")
    return PredictionFrame(
        symbol,
        exchange,
        pd.DataFrame([values], index=index, dtype=float).sort_index(axis=1),
        pd.Series([target_date], index=index),
        pd.Series([digest], index=index),
    )
