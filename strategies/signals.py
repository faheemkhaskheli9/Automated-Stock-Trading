"""Provider-agnostic signal type every strategy (rule-based, manual,
ML-driven) produces, so the risk/order pipeline downstream (Phase 3) only
ever has to understand this one shape."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class Action(str, Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass(frozen=True)
class Signal:
    timestamp: datetime
    action: Action
    confidence: float = 1.0
    reason: str = ""
