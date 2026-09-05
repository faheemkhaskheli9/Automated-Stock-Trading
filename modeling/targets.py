"""Target-spec schema and label builder.

A ``target_spec`` is a JSON dict with a ``type`` and type-specific params::

    {"type": "horizon_close", "horizon": 1}          # next-day close
    {"type": "horizon_return", "horizon": 5}
    {"type": "direction", "horizon": 1}              # 1 if close_{t+h} > close_t
    {"type": "weekday_anchored", "entry_weekday": 0, "exit_weekday": 4}
    {"type": "multistep", "steps": 3}

``build_target`` returns ``(y, target_dates, available_at, task)`` aligned to
the supplied decision index. A daily bar dated D is treated as available at
the next local midnight (matches ``forecasting/features.py``), so a training
row is usable only once its label's ``available_at`` has passed. No Django
imports here.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

TARGET_TYPES = ("horizon_close", "horizon_return", "direction", "weekday_anchored", "multistep")
_REGRESSION = "regression"
_CLASSIFICATION = "classification"
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def _pos_int(value, name, *, minimum=1):
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def validate_spec(spec) -> dict:
    if not isinstance(spec, dict) or "type" not in spec:
        raise ValueError("target_spec must be a dict with a 'type'")
    ttype = spec["type"]
    if ttype not in TARGET_TYPES:
        raise ValueError(f"unknown target type {ttype!r}; known: {TARGET_TYPES}")
    out = {"type": ttype}
    if ttype in ("horizon_close", "horizon_return", "direction"):
        out["horizon"] = _pos_int(spec.get("horizon", 1), f"{ttype}.horizon")
    elif ttype == "weekday_anchored":
        entry = _pos_int(spec.get("entry_weekday", 0), "entry_weekday", minimum=0)
        exit_ = _pos_int(spec.get("exit_weekday", 4), "exit_weekday", minimum=0)
        if entry > 6 or exit_ > 6:
            raise ValueError("weekday values must be 0 (Mon) .. 6 (Sun)")
        if exit_ <= entry:
            raise ValueError("exit_weekday must be after entry_weekday in the same week")
        out.update(entry_weekday=entry, exit_weekday=exit_)
    elif ttype == "multistep":
        out["steps"] = _pos_int(spec.get("steps", 3), "multistep.steps", minimum=2)
    return out


def task_of(spec) -> str:
    return _CLASSIFICATION if validate_spec(spec)["type"] == "direction" else _REGRESSION


def is_multioutput(spec) -> bool:
    return validate_spec(spec)["type"] == "multistep"


def decision_filter(
    spec, index: pd.DatetimeIndex, *, exchange_tz: str = "Asia/Karachi"
) -> pd.DatetimeIndex:
    """Restrict candidate decision timestamps for this target (weekday anchor)."""
    spec = validate_spec(spec)
    if spec["type"] != "weekday_anchored":
        return index
    local = index.tz_convert(ZoneInfo(exchange_tz))
    return index[local.weekday == spec["entry_weekday"]]


def derive_target_date(spec, as_of_date):
    """Session date a forecast made on ``as_of_date`` refers to.

    Only defined for ``weekday_anchored`` (pure calendar arithmetic); the
    other types require the caller to pass an explicit target date, matching
    the ``forecasting`` app's refusal to invent an exchange calendar.
    """
    spec = validate_spec(spec)
    if spec["type"] != "weekday_anchored":
        return None
    return as_of_date + timedelta(days=spec["exit_weekday"] - as_of_date.weekday())


def _avail_series(dates, tz: str) -> pd.Series:
    zone = ZoneInfo(tz)
    return pd.Series(
        [
            (
                pd.Timestamp(datetime.combine(d + timedelta(days=1), time.min), tz=zone)
                if pd.notna(d)
                else pd.NaT
            )
            for d in dates
        ],
        index=getattr(dates, "index", None),
    )


def build_target(
    spec,
    ohlcv: pd.DataFrame,
    *,
    decision_index: pd.DatetimeIndex,
    exchange_tz: str = "Asia/Karachi",
):
    """Return ``(y, target_dates, available_at, task)`` aligned to ``decision_index``."""
    spec = validate_spec(spec)
    ohlcv = ohlcv.sort_index()
    close = ohlcv["close"].astype(float)
    local_dates = pd.Series(ohlcv.index.tz_convert(ZoneInfo(exchange_tz)).date, index=ohlcv.index)
    ttype = spec["type"]

    if ttype in ("horizon_close", "horizon_return", "direction"):
        h = spec["horizon"]
        future_close = close.shift(-h)
        future_date = local_dates.shift(-h)
        if ttype == "horizon_close":
            y = future_close
        elif ttype == "horizon_return":
            y = future_close / close - 1.0
        else:
            y = (future_close > close).astype(float).where(future_close.notna())
        y = y.reindex(decision_index)
        tdates = future_date.reindex(decision_index)
        return y, tdates, _avail_series(tdates, exchange_tz).set_axis(decision_index), task_of(spec)

    if ttype == "multistep":
        n = spec["steps"]
        cols = {f"step_{k}": close.shift(-k) for k in range(1, n + 1)}
        y = pd.DataFrame(cols).reindex(decision_index)
        y = y.where(y.notna().all(axis=1), np.nan)
        tdates = local_dates.shift(-n).reindex(decision_index)
        return y, tdates, _avail_series(tdates, exchange_tz).set_axis(decision_index), _REGRESSION

    # weekday_anchored
    zone = ZoneInfo(exchange_tz)
    local_idx = ohlcv.index.tz_convert(zone)
    iso = local_idx.isocalendar()
    week_key = list(zip(iso["year"].to_numpy(), iso["week"].to_numpy()))
    exit_wd = spec["exit_weekday"]
    exit_close_by_week: dict = {}
    exit_date_by_week: dict = {}
    for i, wd in enumerate(local_idx.weekday):
        if wd == exit_wd:
            exit_close_by_week[week_key[i]] = float(close.iloc[i])
            exit_date_by_week[week_key[i]] = local_dates.iloc[i]
    pos = ohlcv.index.get_indexer(decision_index)
    y_vals, t_vals = [], []
    for p in pos:
        key = week_key[p] if p >= 0 else None
        y_vals.append(exit_close_by_week.get(key, np.nan))
        t_vals.append(exit_date_by_week.get(key, pd.NaT))
    y = pd.Series(y_vals, index=decision_index, dtype=float)
    tdates = pd.Series(t_vals, index=decision_index)
    return y, tdates, _avail_series(tdates, exchange_tz).set_axis(decision_index), _REGRESSION
