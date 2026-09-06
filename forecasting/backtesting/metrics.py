"""Score next-day close forecasts and translate them into a trade log.

Framework-free (numpy only) so it unit-tests cheaply. Every function returns a
plain JSON-serialisable ``dict`` so a caller can persist or render it directly.

``anchor`` throughout is the decision-bar close (``price.close`` of the row the
forecast was made from); ``actual`` is the realised next-session close (the
label). ``predicted`` is the predictor's forecast of that same close.
"""

from __future__ import annotations

from datetime import date

import numpy as np

TRADING_DAYS_PER_YEAR = 252  # same convention as strategies.backtesting.engine


def _finite(*arrays):
    mask = np.ones(len(arrays[0]), dtype=bool)
    for arr in arrays:
        mask &= np.isfinite(np.asarray(arr, dtype=float))
    return mask


def regression_scores(predicted, actual, anchor) -> dict:
    """MAE / RMSE / MAPE / R2 plus directional accuracy and skill-vs-naive.

    The naive baseline is "tomorrow's close equals today's close" (``anchor``);
    ``skill_vs_naive = 1 - mae / naive_mae`` is the headline number - positive
    means the predictor genuinely beats a random walk.
    """
    predicted = np.asarray(predicted, dtype=float)
    actual = np.asarray(actual, dtype=float)
    anchor = np.asarray(anchor, dtype=float)
    mask = _finite(predicted, actual, anchor)
    predicted, actual, anchor = predicted[mask], actual[mask], anchor[mask]
    if not len(actual):
        return {}

    err = predicted - actual
    nonzero = actual != 0
    ss_res = float(np.sum(err**2))
    ss_tot = float(np.sum((actual - actual.mean()) ** 2))
    naive_mae = float(np.mean(np.abs(anchor - actual)))
    mae = float(np.mean(np.abs(err)))
    return {
        "n": int(len(actual)),
        "mae": mae,
        "rmse": float(np.sqrt(np.mean(err**2))),
        "mape": (
            float(np.mean(np.abs(err[nonzero] / actual[nonzero])) * 100) if nonzero.any() else None
        ),
        "r2": (float(1 - ss_res / ss_tot) if ss_tot else None),
        "directional_accuracy": float(
            np.mean(np.sign(predicted - anchor) == np.sign(actual - anchor))
        ),
        "naive_mae": naive_mae,
        "skill_vs_naive": (float(1 - mae / naive_mae) if naive_mae else None),
    }


def trading_translation(
    dates: list[date],
    predicted,
    actual,
    anchor,
    *,
    allow_short: bool = False,
    long_threshold: float = 0.0,
    cost_bps: float = 0.0,
    initial_cash: float = 100_000.0,
) -> dict:
    """ "Long if the forecast is up" replayed against the realised closes.

    ``predicted[i]`` is compared to ``anchor[i]`` to take a position that earns
    ``actual[i] / anchor[i] - 1`` over the next session. A round-trip cost of
    ``cost_bps`` basis points is charged whenever the held position changes.
    """
    predicted = np.asarray(predicted, dtype=float)
    actual = np.asarray(actual, dtype=float)
    anchor = np.asarray(anchor, dtype=float)
    mask = _finite(predicted, actual, anchor)
    predicted, actual, anchor = predicted[mask], actual[mask], anchor[mask]
    kept_dates = [d for d, keep in zip(dates, mask) if keep]
    if not len(actual):
        return {}

    with np.errstate(divide="ignore", invalid="ignore"):
        edge = np.where(anchor > 0, predicted / anchor - 1.0, 0.0)
        step_return = np.where(anchor > 0, actual / anchor - 1.0, 0.0)
    thr = float(long_threshold)
    position = np.where(edge > thr, 1, 0)
    if allow_short:
        position = np.where(edge < -thr, -1, position)

    cost_rate = float(cost_bps) / 10_000.0
    equity = float(initial_cash)
    curve: list[tuple[str, float]] = []
    prev = 0
    wins = trades = 0
    for i in range(len(actual)):
        held = int(position[i])
        if held != prev:
            equity -= equity * cost_rate * abs(held - prev)
        equity *= 1.0 + held * float(step_return[i])
        if held != 0:
            trades += 1
            wins += int(held * step_return[i] > 0)
        prev = held
        curve.append((kept_dates[i].isoformat(), equity))
    if prev != 0:
        equity -= equity * cost_rate * abs(prev)
        curve[-1] = (curve[-1][0], equity)

    total_return = equity / initial_cash - 1.0
    active = step_return[position != 0]
    strat_returns = position.astype(float) * step_return
    peak = np.maximum.accumulate(np.cumprod(1.0 + strat_returns))
    max_dd = (
        float(np.max(1.0 - np.cumprod(1.0 + strat_returns) / peak)) if len(strat_returns) else 0.0
    )
    sharpe = (
        float(strat_returns.mean() / strat_returns.std() * np.sqrt(TRADING_DAYS_PER_YEAR))
        if strat_returns.std()
        else None
    )
    years = len(actual) / TRADING_DAYS_PER_YEAR
    return {
        "n": int(len(actual)),
        "initial_cash": float(initial_cash),
        "final_equity": float(equity),
        "total_return": float(total_return),
        "annualized_return": (
            float((1.0 + total_return) ** (1.0 / years) - 1.0)
            if years > 0 and total_return > -1
            else None
        ),
        "max_drawdown": max_dd,
        "sharpe": sharpe,
        "num_trades": int(trades),
        "hit_rate": (float(wins / trades) if trades else None),
        "exposure": float(np.mean(position != 0)),
        "avg_active_return": (float(active.mean()) if len(active) else None),
        "equity_curve": curve,
    }
