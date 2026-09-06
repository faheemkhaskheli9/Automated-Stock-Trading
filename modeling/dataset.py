"""Point-in-time X / y assembly, pooled across a model's instruments.

The single choke point that joins price history, engineered features and
target labels. Every feature is built as of its own decision timestamp
(``features.build_feature_columns``); a training row survives only if its
label was actually observable by ``train_end`` (``targets`` availability
convention). The train / holdout split is a trailing time-ordered cut - no
shuffle, no k-fold. Walk-forward evaluation is a separate future concern
(see ``forecasting`` Phase C).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from django.conf import settings
from django.utils import timezone

from marketdata.models import PriceBar

from . import features as feature_mod
from . import targets as target_mod


@dataclass
class Dataset:
    X: pd.DataFrame
    feature_names: list[str]
    task: str
    multioutput: bool
    anchor: pd.Series
    symbols: list[str]
    for_training: bool
    y: pd.Series | pd.DataFrame | None = None
    target_dates: pd.Series | None = None
    available_at: pd.Series | None = None
    train_mask: np.ndarray | None = field(default=None)
    holdout_mask: np.ndarray | None = field(default=None)
    instrument_labels: list[str] | None = None


def _tz() -> str:
    return settings.TIME_ZONE


def _midnight(d: date, tz: str) -> datetime:
    return datetime.combine(d + timedelta(days=1), time.min, tzinfo=ZoneInfo(tz))


def _load_history(instrument, cutoff_dt: datetime, tz: str) -> pd.DataFrame:
    rows = list(
        PriceBar.objects.filter(
            instrument=instrument,
            timeframe=PriceBar.Timeframe.DAILY,
            timestamp__lte=cutoff_dt,
        )
        .order_by("timestamp")
        .values("timestamp", "open", "high", "low", "close", "volume", "is_anomaly")
    )
    if not rows:
        raise ValueError(f"No daily price history for {instrument.symbol} ({instrument.exchange})")
    idx = pd.DatetimeIndex([r["timestamp"] for r in rows]).tz_convert(ZoneInfo(tz))
    df = pd.DataFrame(rows, index=idx)
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = df[col].astype(float)
    local_dates = list(idx.date)
    if len(set(local_dates)) != len(local_dates):
        raise ValueError(f"{instrument.symbol}: multiple daily bars for one local session date")
    if df["is_anomaly"].any():
        raise ValueError(
            f"{instrument.symbol}: history contains flagged anomalies - resolve them first"
        )
    ohlc = df[["open", "high", "low", "close"]]
    if (ohlc <= 0).to_numpy().any() or (df["volume"] < 0).any():
        raise ValueError(f"{instrument.symbol}: non-positive prices or negative volume in history")
    return df[["open", "high", "low", "close", "volume"]]


def _decision_index(ohlcv, start, end, tz) -> pd.DatetimeIndex:
    local = pd.Series(ohlcv.index.tz_convert(ZoneInfo(tz)).date, index=ohlcv.index)
    keep = pd.Series(True, index=ohlcv.index)
    if start is not None:
        keep &= local >= start
    if end is not None:
        keep &= local <= end
    return ohlcv.index[keep.to_numpy()]


def build_dataset(
    model,
    *,
    start: date | None = None,
    end: date | None = None,
    for_training: bool = True,
    instruments=None,
    single_row_as_of: date | None = None,
) -> Dataset:
    tz = _tz()
    instruments = list(instruments if instruments is not None else model.instruments.all())
    if not instruments:
        raise ValueError("The model has no instruments configured")

    start = start or model.train_start
    end = end or model.train_end
    feature_spec = feature_mod.validate_spec(model.feature_spec)
    target_spec = target_mod.validate_spec(model.target_spec)
    task = target_mod.task_of(target_spec)
    multioutput = target_mod.is_multioutput(target_spec)

    if for_training:
        cutoff_dt = _midnight(end, tz) if end else timezone.now()
    else:
        as_of = single_row_as_of or timezone.localdate()
        cutoff_dt = _midnight(as_of, tz)

    x_parts, anchor_parts, label_parts = [], [], []
    tdate_parts, avail_parts, inst_labels = [], [], []

    for instrument in instruments:
        ohlcv = _load_history(instrument, cutoff_dt, tz)

        if for_training:
            didx = _decision_index(ohlcv, start, end, tz)
        else:
            eligible = ohlcv.index[
                pd.Series(ohlcv.index.tz_convert(ZoneInfo(tz)).date, index=ohlcv.index)
                <= (single_row_as_of or timezone.localdate())
            ]
            if len(eligible) == 0:
                raise ValueError(f"No {instrument.symbol} bar on or before {single_row_as_of}")
            didx = eligible[-1:]

        didx = target_mod.decision_filter(target_spec, didx, exchange_tz=tz)
        if len(didx) == 0:
            if not for_training:
                raise ValueError(
                    "The chosen as-of date is not this target's entry weekday - "
                    "pick a date matching entry_weekday."
                )
            continue

        cols = feature_mod.build_feature_columns(
            feature_spec,
            ohlcv,
            symbol=instrument.symbol,
            exchange=instrument.exchange,
            decision_index=didx,
        )
        x_parts.append(cols)
        anchor_parts.append(
            pd.Series(ohlcv["close"].reindex(didx).to_numpy(), index=didx, name="anchor")
        )
        inst_labels.extend([instrument.symbol] * len(didx))

        if for_training:
            y, tdates, avail, _ = target_mod.build_target(
                target_spec, ohlcv, decision_index=didx, exchange_tz=tz
            )
            label_parts.append(y)
            tdate_parts.append(tdates)
            avail_parts.append(avail)

    if not x_parts:
        raise ValueError("No usable decision rows for this configuration and date range")

    X = pd.concat(x_parts, axis=0)
    feature_names = sorted(X.columns)
    X = X.reindex(columns=feature_names)
    anchor = pd.concat(anchor_parts, axis=0)

    order = np.argsort(X.index.to_numpy(), kind="stable")
    X = X.iloc[order]
    anchor = anchor.iloc[order]
    inst_labels = [inst_labels[i] for i in order]

    ds = Dataset(
        X=X,
        feature_names=feature_names,
        task=task,
        multioutput=multioutput,
        anchor=anchor,
        symbols=[i.symbol for i in instruments],
        for_training=for_training,
        instrument_labels=inst_labels,
    )
    if not for_training:
        return ds

    y = pd.concat(label_parts, axis=0).iloc[order]
    tdates = pd.concat(tdate_parts, axis=0).iloc[order]
    avail = pd.concat(avail_parts, axis=0).iloc[order]

    end_cutoff = _midnight(end, tz) if end else timezone.now()
    label_ok = y.notna().all(axis=1) if hasattr(y, "columns") else y.notna()
    avail_ok = avail.notna() & (avail <= pd.Timestamp(end_cutoff))
    keep = (label_ok & avail_ok).to_numpy()
    if keep.sum() < 10:
        raise ValueError(
            f"Only {int(keep.sum())} usable training rows after the leakage filter - "
            "widen the date range or import more history"
        )
    X, y, anchor = ds.X.loc[keep], y.loc[keep], ds.anchor.loc[keep]
    tdates, avail = tdates.loc[keep], avail.loc[keep]
    inst_labels = [lab for lab, k in zip(ds.instrument_labels, keep) if k]

    n = len(X)
    n_holdout = min(max(int(math.ceil(n * model.holdout_fraction)), 1), n - 1)
    holdout_mask = np.zeros(n, dtype=bool)
    holdout_mask[-n_holdout:] = True

    ds.X, ds.y, ds.anchor = X, y, anchor
    ds.target_dates, ds.available_at = tdates, avail
    ds.instrument_labels = inst_labels
    ds.train_mask = ~holdout_mask
    ds.holdout_mask = holdout_mask
    return ds
