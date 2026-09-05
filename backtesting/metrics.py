"""Turn a model's forecasts into positions, then into a trade log + equity.

Everything here is framework-free (numpy only) so it unit-tests cheaply.
Forecast-accuracy scoring is *not* re-implemented - ``engine`` calls
``modeling.metrics.regression_metrics`` / ``classification_metrics`` for that.
Trading-performance ratios (CAGR, drawdown, Sharpe, win rate) are read off
``strategies.backtesting.engine.BacktestResult`` in ``engine`` rather than
duplicated.
"""

from __future__ import annotations

from datetime import date

import numpy as np

# target types this module knows how to translate
CLOSE_VS_ANCHOR = "horizon_close"
RETURN_THRESHOLD = "horizon_return"
DIRECTION = "direction"


def positions_from_forecast(
    target_type: str,
    predicted: np.ndarray,
    anchor: np.ndarray,
    *,
    long_threshold: float = 0.0,
    allow_short: bool = False,
    proba_up: np.ndarray | None = None,
) -> np.ndarray:
    """Map each forecast to a position in ``{-1, 0, 1}``.

    ``anchor`` is the decision-bar close. For ``horizon_close`` the forecast
    is a price, compared as a fractional gap over the anchor; for
    ``horizon_return`` it is already a return; for ``direction`` the class
    (or ``proba_up`` when available) is used.
    """
    predicted = np.asarray(predicted, dtype=float)
    anchor = np.asarray(anchor, dtype=float)
    thr = float(long_threshold)

    if target_type == DIRECTION:
        base = proba_up if proba_up is not None else predicted
        signal = np.asarray(base, dtype=float) - 0.5
        long_hit, short_hit = signal > thr, signal < -thr
    elif target_type == RETURN_THRESHOLD:
        long_hit, short_hit = predicted > thr, predicted < -thr
    else:  # CLOSE_VS_ANCHOR
        with np.errstate(divide="ignore", invalid="ignore"):
            edge = np.where(anchor > 0, predicted / anchor - 1.0, 0.0)
        long_hit, short_hit = edge > thr, edge < -thr

    pos = np.where(long_hit, 1, 0)
    if allow_short:
        pos = np.where(short_hit, -1, pos)
    return pos.astype(int)


def simulate_instrument(
    dates: list[date],
    closes: np.ndarray,
    positions: np.ndarray,
    *,
    initial_cash: float,
    commission_bps: float = 0.0,
    slippage_bps: float = 0.0,
) -> tuple[list[tuple[date, float]], list[dict]]:
    """Replay one instrument's positions against its decision-bar closes.

    ``positions[i]`` is the position taken at ``closes[i]`` and carried until
    ``closes[i + 1]``. A round-trip cost (commission + slippage) is charged on
    every change in held position. Returns ``(equity_curve, trades)`` where a
    trade is one contiguous non-flat run (entry at its first close, exit at
    the close where it ends or flips).
    """
    closes = np.asarray(closes, dtype=float)
    positions = np.asarray(positions, dtype=int)
    n = len(closes)
    cost_rate = (float(commission_bps) + float(slippage_bps)) / 10_000.0

    equity = float(initial_cash)
    curve: list[tuple[date, float]] = []
    if n:
        curve.append((dates[0], equity))

    prev = 0
    for i in range(1, n):
        held = int(positions[i - 1])
        if held != prev:
            equity -= equity * cost_rate * abs(held - prev)
        ret = (closes[i] / closes[i - 1] - 1.0) if closes[i - 1] else 0.0
        equity *= 1.0 + held * ret
        prev = held
        curve.append((dates[i], equity))
    if prev != 0:  # close out at the last bar
        equity -= equity * cost_rate * abs(prev)
        curve[-1] = (curve[-1][0], equity)

    trades = (
        _trade_log(dates, closes, positions, initial_cash / max(len(closes), 1), cost_rate)
        if n
        else []
    )
    return curve, trades


def _trade_log(dates, closes, positions, alloc, cost_rate) -> list[dict]:
    trades: list[dict] = []
    n = len(closes)
    i = 0
    # held position over interval [k, k+1] is positions[k]; last usable k is n-2
    while i < n - 1:
        v = int(positions[i])
        if v == 0:
            i += 1
            continue
        j = i
        while j + 1 < n - 1 and int(positions[j + 1]) == v:
            j += 1
        entry_price = float(closes[i])
        exit_price = float(closes[j + 1])
        shares = v * (alloc / entry_price if entry_price else 0.0)
        fees = cost_rate * abs(shares) * (entry_price + exit_price)
        gross = shares * (exit_price - entry_price)
        trades.append(
            {
                "direction": v,
                "entry_date": dates[i],
                "exit_date": dates[j + 1],
                "entry_price": entry_price,
                "exit_price": exit_price,
                "shares": shares,
                "fees": fees,
                "pnl": gross - fees,
                "return_pct": ((exit_price / entry_price - 1.0) * v if entry_price else 0.0),
            }
        )
        i = j + 1
    return trades


def combine_equity_curves(
    curves: list[list[tuple[date, float]]], initial_cash: float
) -> list[tuple[date, float]]:
    """Sum per-instrument equity curves onto the union of their dates.

    Each instrument starts at ``initial_cash / n``; before its first point
    that capital sits in cash, after its last point it holds its final equity
    (forward fill)."""
    curves = [c for c in curves if c]
    if not curves:
        return []
    per = initial_cash / len(curves)
    all_dates = sorted({d for curve in curves for d, _ in curve})
    combined: list[tuple[date, float]] = []
    for d in all_dates:
        total = 0.0
        for curve in curves:
            value = per
            for cd, cv in curve:
                if cd <= d:
                    value = cv
                else:
                    break
            total += value
        combined.append((d, total))
    return combined
