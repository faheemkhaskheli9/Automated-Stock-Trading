"""Reference rule-based (technical indicator) strategies - deterministic and
easy to reason about/backtest, unlike the ML path."""

import pandas as pd

from marketdata.providers.base import Bar

from .base import BaseStrategy
from .registry import register_strategy
from .signals import Action, Signal


def _closes(bars: list[Bar]) -> pd.Series:
    return pd.Series([bar.close for bar in bars])


@register_strategy("ma_crossover")
class MovingAverageCrossoverStrategy(BaseStrategy):
    """BUY when the fast MA crosses above the slow MA, SELL on the reverse
    cross, HOLD otherwise (including while there isn't enough history for
    both averages yet)."""

    display_name = "Moving Average Crossover"

    def __init__(self, fast_period: int = 10, slow_period: int = 30, **params):
        super().__init__(fast_period=fast_period, slow_period=slow_period, **params)
        self.fast_period = fast_period
        self.slow_period = slow_period

    def generate_signals(self, bars: list[Bar]) -> list[Signal]:
        if len(bars) < self.slow_period + 1:
            return [
                Signal(bar.timestamp, Action.HOLD, reason="insufficient history") for bar in bars
            ]

        closes = _closes(bars)
        fast = closes.rolling(self.fast_period).mean()
        slow = closes.rolling(self.slow_period).mean()
        above = fast > slow
        # A crossover happened where "above" differs from the previous bar's "above".
        crossed = above.ne(above.shift(1))

        signals = []
        for i, bar in enumerate(bars):
            if pd.isna(fast.iloc[i]) or pd.isna(slow.iloc[i]) or i == 0 or not crossed.iloc[i]:
                signals.append(Signal(bar.timestamp, Action.HOLD))
            elif above.iloc[i]:
                signals.append(
                    Signal(bar.timestamp, Action.BUY, reason="fast MA crossed above slow MA")
                )
            else:
                signals.append(
                    Signal(bar.timestamp, Action.SELL, reason="fast MA crossed below slow MA")
                )
        return signals


@register_strategy("rsi")
class RSIStrategy(BaseStrategy):
    """BUY when RSI drops below `oversold`, SELL when it rises above
    `overbought`, HOLD otherwise."""

    display_name = "RSI Threshold"

    def __init__(self, period: int = 14, oversold: float = 30, overbought: float = 70, **params):
        super().__init__(period=period, oversold=oversold, overbought=overbought, **params)
        self.period = period
        self.oversold = oversold
        self.overbought = overbought

    def generate_signals(self, bars: list[Bar]) -> list[Signal]:
        if len(bars) < self.period + 1:
            return [
                Signal(bar.timestamp, Action.HOLD, reason="insufficient history") for bar in bars
            ]

        rsi = _rsi(_closes(bars), self.period)

        signals = []
        for i, bar in enumerate(bars):
            value = rsi.iloc[i]
            if pd.isna(value):
                signals.append(Signal(bar.timestamp, Action.HOLD))
            elif value < self.oversold:
                signals.append(
                    Signal(bar.timestamp, Action.BUY, reason=f"RSI {value:.1f} < {self.oversold}")
                )
            elif value > self.overbought:
                signals.append(
                    Signal(
                        bar.timestamp, Action.SELL, reason=f"RSI {value:.1f} > {self.overbought}"
                    )
                )
            else:
                signals.append(Signal(bar.timestamp, Action.HOLD))
        return signals


def _rsi(closes: pd.Series, period: int) -> pd.Series:
    delta = closes.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()

    rsi = pd.Series(index=closes.index, dtype=float)
    no_movement = (avg_gain == 0) & (avg_loss == 0)  # flat window: conventionally 50
    no_losses = (avg_loss == 0) & (avg_gain != 0)  # only gains in window: 100
    normal = avg_gain.notna() & ~no_movement & ~no_losses

    rsi[no_movement] = 50.0
    rsi[no_losses] = 100.0
    rs = avg_gain[normal] / avg_loss[normal]
    rsi[normal] = 100 - (100 / (1 + rs))
    return rsi
