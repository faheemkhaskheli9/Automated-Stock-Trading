"""ML-driven signal source.

The training/feature-engineering pipeline is explicitly out of scope for
now (see docs/PLAN.md, Phase 2) - there isn't yet enough historical PriceBar
data accumulated to train anything meaningful. This wires the interface so
a real model becomes a drop-in later: point `model_path` at a joblib-
dumped model exposing `.predict(features) -> array of -1/0/1`, and this
strategy will use it. Until then it degrades to HOLD rather than pretending
to have a working model.
"""

import logging
from pathlib import Path

from marketdata.providers.base import Bar

from .base import BaseStrategy
from .registry import register_strategy
from .signals import Action, Signal

logger = logging.getLogger(__name__)

_PREDICTION_TO_ACTION = {1: Action.BUY, 0: Action.HOLD, -1: Action.SELL}


@register_strategy("ml_model")
class MLModelStrategy(BaseStrategy):
    display_name = "ML Model"

    def __init__(self, model_path: str | None = None, lookback: int = 30, **params):
        super().__init__(model_path=model_path, lookback=lookback, **params)
        self.model_path = model_path
        self.lookback = lookback
        self._model = self._load_model()

    def _load_model(self):
        if not self.model_path:
            return None
        path = Path(self.model_path)
        if not path.exists():
            logger.warning("MLModelStrategy: model file not found at %s - will HOLD", path)
            return None
        import joblib

        return joblib.load(path)

    def generate_signals(self, bars: list[Bar]) -> list[Signal]:
        if self._model is None:
            return [
                Signal(bar.timestamp, Action.HOLD, reason="no model configured") for bar in bars
            ]

        signals = []
        for i, bar in enumerate(bars):
            window = bars[max(0, i - self.lookback + 1) : i + 1]
            if len(window) < self.lookback:
                signals.append(Signal(bar.timestamp, Action.HOLD, reason="insufficient history"))
                continue
            features = self._features(window)
            prediction = int(self._model.predict([features])[0])
            action = _PREDICTION_TO_ACTION.get(prediction, Action.HOLD)
            signals.append(Signal(bar.timestamp, action, reason=f"model prediction={prediction}"))
        return signals

    @staticmethod
    def _features(window: list[Bar]) -> list[float]:
        """Placeholder feature vector (raw closes) - replace once a real
        training/feature pipeline exists."""
        return [bar.close for bar in window]
