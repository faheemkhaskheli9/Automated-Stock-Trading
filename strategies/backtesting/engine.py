"""Replays a strategy's signals against historical bars for one instrument
and reports performance metrics - what proves a strategy is worth running
live (Phase 3) before it ever touches an order.

Long-only, single-instrument, all-in/all-out position sizing: this is
intentionally the simplest thing that lets any BaseStrategy be validated
end-to-end. Position sizing/risk limits are a Phase 3 concern (the `risk`
app applies them to live trading, not to this historical replay).
"""

import math
from dataclasses import dataclass, field
from datetime import datetime

from marketdata.providers.base import Bar

from ..base import BaseStrategy
from ..signals import Action

TRADING_DAYS_PER_YEAR = 252  # approx PSX sessions/year, same convention as most equity markets


@dataclass(frozen=True)
class Trade:
    entry_time: datetime
    entry_price: float
    exit_time: datetime
    exit_price: float
    shares: int

    @property
    def pnl(self) -> float:
        return (self.exit_price - self.entry_price) * self.shares


@dataclass
class BacktestResult:
    initial_cash: float
    final_equity: float
    equity_curve: list[tuple[datetime, float]] = field(default_factory=list)
    trades: list[Trade] = field(default_factory=list)
    open_position_shares: int = 0

    @property
    def total_return(self) -> float:
        if self.initial_cash == 0:
            return 0.0
        return self.final_equity / self.initial_cash - 1

    @property
    def num_trades(self) -> int:
        return len(self.trades)

    @property
    def win_rate(self) -> float | None:
        if not self.trades:
            return None
        wins = sum(1 for t in self.trades if t.pnl > 0)
        return wins / len(self.trades)

    @property
    def cagr(self) -> float:
        if len(self.equity_curve) < 2 or self.initial_cash <= 0 or self.final_equity <= 0:
            return 0.0
        years = (len(self.equity_curve) - 1) / TRADING_DAYS_PER_YEAR
        if years <= 0:
            return 0.0
        return (self.final_equity / self.initial_cash) ** (1 / years) - 1

    @property
    def max_drawdown(self) -> float:
        if not self.equity_curve:
            return 0.0
        peak = self.equity_curve[0][1]
        max_dd = 0.0
        for _, equity in self.equity_curve:
            peak = max(peak, equity)
            if peak > 0:
                max_dd = max(max_dd, (peak - equity) / peak)
        return max_dd

    @property
    def sharpe(self) -> float | None:
        if len(self.equity_curve) < 3:
            return None
        returns = []
        for (_, prev), (_, curr) in zip(self.equity_curve, self.equity_curve[1:]):
            if prev > 0:
                returns.append(curr / prev - 1)
        if len(returns) < 2:
            return None
        mean = sum(returns) / len(returns)
        variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
        std = math.sqrt(variance)
        if std == 0:
            return None
        return (mean / std) * math.sqrt(TRADING_DAYS_PER_YEAR)


def run_backtest(
    strategy: BaseStrategy, bars: list[Bar], initial_cash: float = 100_000.0
) -> BacktestResult:
    if not bars:
        return BacktestResult(initial_cash=initial_cash, final_equity=initial_cash)

    signals = strategy.generate_signals(bars)
    if len(signals) != len(bars):
        raise ValueError(
            f"{type(strategy).__name__}.generate_signals returned {len(signals)} signals "
            f"for {len(bars)} bars - must be one per bar."
        )

    cash = initial_cash
    shares = 0
    entry_price = None
    entry_time = None
    trades: list[Trade] = []
    equity_curve: list[tuple[datetime, float]] = []

    for bar, signal in zip(bars, signals):
        if signal.action == Action.BUY and shares == 0 and cash > 0:
            shares = int(cash // float(bar.close))
            if shares > 0:
                cash -= shares * float(bar.close)
                entry_price = float(bar.close)
                entry_time = bar.timestamp
        elif signal.action == Action.SELL and shares > 0:
            cash += shares * float(bar.close)
            trades.append(
                Trade(
                    entry_time=entry_time,
                    entry_price=entry_price,
                    exit_time=bar.timestamp,
                    exit_price=float(bar.close),
                    shares=shares,
                )
            )
            shares = 0
            entry_price = None
            entry_time = None

        equity_curve.append((bar.timestamp, cash + shares * float(bar.close)))

    final_equity = equity_curve[-1][1]
    return BacktestResult(
        initial_cash=initial_cash,
        final_equity=final_equity,
        equity_curve=equity_curve,
        trades=trades,
        open_position_shares=shares,
    )
