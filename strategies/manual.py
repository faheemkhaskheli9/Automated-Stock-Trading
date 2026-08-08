"""Manual signal source: an operator enters BUY/SELL/HOLD decisions (via
admin/API) instead of a formula computing them - but it still flows through
the exact same Signal/backtest/risk/order pipeline as any other strategy.
"""

from marketdata.providers.base import Bar

from .base import BaseStrategy
from .models import ManualSignal
from .registry import register_strategy
from .signals import Action, Signal


@register_strategy("manual")
class ManualSignalStrategy(BaseStrategy):
    display_name = "Manual Signal"

    def __init__(self, instrument_id: int | None = None, **params):
        super().__init__(instrument_id=instrument_id, **params)
        if instrument_id is None:
            raise ValueError("ManualSignalStrategy requires an instrument_id param")
        self.instrument_id = instrument_id

    def generate_signals(self, bars: list[Bar]) -> list[Signal]:
        if not bars:
            return []

        dates = [bar.timestamp.date() for bar in bars]
        entries = ManualSignal.objects.filter(
            instrument_id=self.instrument_id, date__in=dates
        ).values_list("date", "action")
        by_date = dict(entries)

        signals = []
        for bar in bars:
            action = by_date.get(bar.timestamp.date())
            if action is None:
                signals.append(
                    Signal(bar.timestamp, Action.HOLD, reason="no manual entry for this date")
                )
            else:
                signals.append(Signal(bar.timestamp, Action(action), reason="manual entry"))
        return signals
