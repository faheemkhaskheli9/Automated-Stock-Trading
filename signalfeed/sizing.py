"""Per-signal position sizing - advisory only.

``signalfeed`` never places an order (PSX has no self-serve order API; live
trading is a separate, gated phase). This module turns a *deliverable* weekly
call into a suggested share count / notional so the operator has a starting
point instead of eyeballing it - it is a hint printed on the card and in the
delivered message, nothing more.

Method (deliberately simple, and bounded so a near-coin-flip model never
suggests a big bet):

    edge      = max(0, 2 * directional_accuracy - 1)   # 0 at 50%, 1 at 100%
    fraction  = kelly_fraction * edge                   # fractional-Kelly on the edge
    fraction  = min(fraction, max_position_pct / 100)   # hard cap
    notional  = capital * fraction
    shares    = floor(notional / reference_close)

``kelly_fraction == 0`` disables the edge scaling and sizes flat at the cap
whenever a call is deliverable. Magnitude (``expected_return_pct``) is *not*
used as a divisor - that is the classic Kelly blow-up for small moves; the
flat-vs-directional decision already filtered tiny moves out upstream.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

_ACTIONABLE = ("up", "down")


@dataclass(frozen=True)
class SizeSuggestion:
    fraction: float  # of ``capital``, in [0, max_position_pct / 100]
    notional: float  # ``capital * fraction``
    shares: int  # ``floor(notional / reference_close)``
    basis: dict  # snapshot of every input, for the audit trail


def suggest_size(
    *,
    direction: str,
    directional_accuracy: float | None,
    capital: float,
    max_position_pct: float,
    kelly_fraction: float,
    reference_close: float | None,
) -> SizeSuggestion | None:
    """A sizing hint for one deliverable call, or ``None`` when sizing is
    disabled (``capital <= 0``) or the call is not actionable (FLAT)."""
    capital = float(capital or 0.0)
    if capital <= 0 or direction not in _ACTIONABLE:
        return None

    cap_fraction = max(0.0, min(float(max_position_pct) / 100.0, 1.0))
    acc = 0.5 if directional_accuracy is None else float(directional_accuracy)
    edge = max(0.0, 2.0 * acc - 1.0)
    kf = max(0.0, float(kelly_fraction))

    raw = cap_fraction if kf == 0 else kf * edge
    fraction = max(0.0, min(raw, cap_fraction))
    notional = capital * fraction

    ref = float(reference_close) if reference_close else 0.0
    shares = int(math.floor(notional / ref)) if ref > 0 else 0

    basis = {
        "capital": round(capital, 2),
        "max_position_pct": float(max_position_pct),
        "kelly_fraction": float(kelly_fraction),
        "directional_accuracy": directional_accuracy,
        "edge": round(edge, 4),
        "reference_close": ref or None,
    }
    return SizeSuggestion(
        fraction=round(fraction, 4),
        notional=round(notional, 2),
        shares=shares,
        basis=basis,
    )
