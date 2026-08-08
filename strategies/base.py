"""The one interface every signal source implements - rule-based, manual,
or ML-driven. Downstream code (backtester now, risk/order pipeline in
Phase 3) only ever depends on this, never on a concrete strategy class.
"""

from abc import ABC, abstractmethod

from marketdata.providers.base import Bar

from .signals import Signal


class BaseStrategy(ABC):
    #: Unique registry key, e.g. "ma_crossover". Set by @register_strategy.
    key: str = ""
    #: Human-readable name shown in admin/UI.
    display_name: str = ""

    def __init__(self, **params):
        self.params = params

    @abstractmethod
    def generate_signals(self, bars: list[Bar]) -> list[Signal]:
        """Given `bars` (oldest first, one instrument's history), return one
        Signal per bar, aligned by index (signals[i] corresponds to bars[i]).

        Vectorized-per-history rather than "give me just the latest signal"
        so the same call works unchanged for backtesting (replay the whole
        list) and live use (callers just take signals[-1])."""
