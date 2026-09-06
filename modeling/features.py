"""Feature-spec schema and the point-in-time feature builder.

A ``feature_spec`` is a JSON list of source descriptors, each a dict with a
``kind`` and kind-specific params::

    [
      {"kind": "ohlc", "fields": ["open", "close"], "lags": [0, 1, 2]},
      {"kind": "return", "periods": [1, 5]},
      {"kind": "technical", "names": ["rsi_14", "macd"]},
      {"kind": "strategy_signal", "strategy_key": "rsi", "params": {"period": 14}},
      {"kind": "calendar", "features": ["weekday", "month"]},
    ]

Every source is evaluated **as of each decision timestamp** using only the
price prefix up to and including that bar - no look-ahead. Missing warmup
values are left as NaN; a ``SimpleImputer`` in the training pipeline fills
them using training-row statistics only.

``validate_spec`` intentionally has no Django imports so ``TradingModel.clean``
can call it cheaply; it raises ``ValueError`` which callers wrap.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

OHLC_FIELDS = ("open", "high", "low", "close", "volume")
CALENDAR_FEATURES = ("weekday", "month", "day_of_month", "week_of_year", "quarter")
FEATURE_KINDS = (
    "ohlc",
    "return",
    "technical",
    "research",
    "strategy_signal",
    "manual_signal",
    "calendar",
)
_ACTION_TO_NUM = {"buy": 1.0, "sell": -1.0, "hold": 0.0}


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------
def _int_list(value, name):
    if not isinstance(value, (list, tuple)) or not value:
        raise ValueError(f"{name} must be a non-empty list")
    out = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int):
            raise ValueError(f"{name} entries must be integers, got {item!r}")
        out.append(item)
    return out


def validate_spec(spec) -> list[dict]:
    """Return a normalised copy of ``spec`` or raise ``ValueError``."""
    if not isinstance(spec, list) or not spec:
        raise ValueError("feature_spec must be a non-empty list of source descriptors")

    normalised: list[dict] = []
    for i, raw in enumerate(spec):
        if not isinstance(raw, dict) or "kind" not in raw:
            raise ValueError(f"feature_spec[{i}] must be a dict with a 'kind'")
        kind = raw["kind"]
        if kind not in FEATURE_KINDS:
            raise ValueError(f"feature_spec[{i}]: unknown kind {kind!r}; known: {FEATURE_KINDS}")
        item = {"kind": kind}

        if kind == "ohlc":
            fields = raw.get("fields") or ["close"]
            bad = set(fields) - set(OHLC_FIELDS)
            if bad:
                raise ValueError(f"ohlc.fields has unknown fields {sorted(bad)}")
            lags = _int_list(raw.get("lags", [0]), "ohlc.lags")
            if any(k < 0 for k in lags):
                raise ValueError("ohlc.lags must be >= 0")
            item.update(fields=list(fields), lags=lags)

        elif kind == "return":
            periods = _int_list(raw.get("periods", [1]), "return.periods")
            if any(p <= 0 for p in periods):
                raise ValueError("return.periods must be >= 1")
            item.update(periods=periods)

        elif kind == "technical":
            names = raw.get("names")
            if names is not None and (not isinstance(names, list) or not names):
                raise ValueError("technical.names must be a non-empty list when given")
            item.update(names=list(names) if names else None)

        elif kind == "research":
            providers = raw.get("providers") or ["news"]
            if not isinstance(providers, list) or not providers:
                raise ValueError("research.providers must be a non-empty list")
            item.update(providers=list(providers))

        elif kind == "strategy_signal":
            has_id = raw.get("strategy_id") is not None
            has_key = bool(raw.get("strategy_key"))
            if has_id == has_key:
                raise ValueError(
                    "strategy_signal needs exactly one of 'strategy_id' or 'strategy_key'"
                )
            params = raw.get("params", {})
            if not isinstance(params, dict):
                raise ValueError("strategy_signal.params must be an object")
            item.update(
                strategy_id=raw.get("strategy_id"),
                strategy_key=raw.get("strategy_key"),
                params=params,
                alias=raw.get("alias"),
            )

        elif kind == "manual_signal":
            pass

        elif kind == "calendar":
            feats = raw.get("features") or ["weekday"]
            bad = set(feats) - set(CALENDAR_FEATURES)
            if bad:
                raise ValueError(f"calendar.features has unknown entries {sorted(bad)}")
            item.update(features=list(feats))

        normalised.append(item)
    return normalised


# --------------------------------------------------------------------------
# Building
# --------------------------------------------------------------------------
def build_feature_columns(
    spec: list[dict],
    ohlcv: pd.DataFrame,
    *,
    symbol: str,
    exchange: str,
    decision_index: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Assemble the feature matrix for one instrument.

    ``ohlcv`` is ascending, tz-aware-indexed, columns open/high/low/close/
    volume. ``decision_index`` is the subset of ``ohlcv.index`` to emit rows
    for. Raises ``ValueError`` on a duplicate feature-column name across
    sources.
    """
    spec = validate_spec(spec)
    ohlcv = ohlcv.sort_index()
    frames: list[pd.DataFrame] = []
    for item in spec:
        frames.append(_build_one(item, ohlcv, symbol, exchange, decision_index))

    out = pd.concat(frames, axis=1) if frames else pd.DataFrame(index=decision_index)
    dupes = out.columns[out.columns.duplicated()].unique().tolist()
    if dupes:
        raise ValueError(
            f"feature_spec produces duplicate columns {dupes}; use 'alias' to disambiguate"
        )
    return out.reindex(decision_index).astype(float)


def _build_one(item, ohlcv, symbol, exchange, decision_index) -> pd.DataFrame:
    kind = item["kind"]
    if kind == "ohlc":
        cols = {
            f"ohlc.{field}_lag_{k}": ohlcv[field].shift(k)
            for field in item["fields"]
            for k in item["lags"]
        }
        return pd.DataFrame(cols).reindex(decision_index)

    if kind == "return":
        close = ohlcv["close"]
        cols = {f"return.{p}": close / close.shift(p) - 1.0 for p in item["periods"]}
        return pd.DataFrame(cols).reindex(decision_index)

    if kind == "technical":
        return _technical_columns(ohlcv, decision_index, item["names"])

    if kind == "research":
        return _research_columns(symbol, exchange, decision_index, item["providers"])

    if kind == "strategy_signal":
        return _strategy_signal_column(item, ohlcv, symbol, exchange, decision_index)

    if kind == "manual_signal":
        return _manual_signal_column(symbol, exchange, decision_index)

    if kind == "calendar":
        return _calendar_columns(decision_index, item["features"])

    raise ValueError(f"unhandled feature kind {kind!r}")  # pragma: no cover


def _technical_columns(ohlcv, decision_index, names) -> pd.DataFrame:
    from research.providers.technical import technical_features

    wanted = None
    if names:
        wanted = {n if n.startswith("technical.") else f"technical.{n}" for n in names}

    positions = ohlcv.index.get_indexer(decision_index)
    records = []
    for pos in positions:
        if pos < 0:
            records.append({})
            continue
        feats = technical_features(ohlcv.iloc[: pos + 1])
        if wanted is not None:
            feats = {k: v for k, v in feats.items() if k in wanted}
        records.append(feats)
    frame = pd.DataFrame.from_records(records, index=decision_index)
    if wanted is not None:
        frame = frame.reindex(columns=sorted(wanted))
    return frame


def _research_columns(symbol, exchange, decision_index, providers) -> pd.DataFrame:
    from research.services import build_feature_bundle

    records = []
    for as_of in decision_index:
        bundle = build_feature_bundle(
            symbol, as_of.to_pydatetime(), exchange=exchange, provider_keys=list(providers)
        )
        records.append(dict(bundle.features))
    return pd.DataFrame.from_records(records, index=decision_index)


def _strategy_signal_column(item, ohlcv, symbol, exchange, decision_index) -> pd.DataFrame:
    from marketdata.providers.base import Bar

    strategy, key = _load_strategy(item)
    bars = [
        Bar(
            timestamp=ts.to_pydatetime(),
            open=float(row.open),
            high=float(row.high),
            low=float(row.low),
            close=float(row.close),
            volume=float(row.volume),
        )
        for ts, row in ohlcv.iterrows()
    ]
    signals = strategy.generate_signals(bars)
    by_ts = {
        pd.Timestamp(sig.timestamp): _ACTION_TO_NUM.get(
            getattr(sig.action, "value", sig.action), 0.0
        )
        for sig in signals
    }
    name = f"signal.{item.get('alias') or key}"
    series = pd.Series(
        [by_ts.get(ts, np.nan) for ts in decision_index], index=decision_index, name=name
    )
    return series.to_frame()


def _load_strategy(item):
    from strategies.registry import get_strategy_class

    if item.get("strategy_id") is not None:
        from strategies.models import Strategy

        model = Strategy.objects.get(pk=item["strategy_id"])
        return model.build(), model.key
    key = item["strategy_key"]
    return get_strategy_class(key)(**(item.get("params") or {})), key


def _manual_signal_column(symbol, exchange, decision_index) -> pd.DataFrame:
    from strategies.models import ManualSignal

    rows = ManualSignal.objects.filter(
        instrument__symbol=symbol, instrument__exchange=exchange
    ).values_list("date", "action")
    by_date = {date: _ACTION_TO_NUM.get(action, 0.0) for date, action in rows}
    values = [by_date.get(ts.date(), np.nan) for ts in decision_index]
    return pd.Series(values, index=decision_index, name="signal.manual").to_frame()


def _calendar_columns(decision_index, features) -> pd.DataFrame:
    idx = decision_index
    src = {
        "weekday": idx.weekday,
        "month": idx.month,
        "day_of_month": idx.day,
        "week_of_year": idx.isocalendar().week.to_numpy(),
        "quarter": idx.quarter,
    }
    return pd.DataFrame(
        {f"calendar.{name}": np.asarray(src[name], dtype=float) for name in features},
        index=decision_index,
    )
