"""The quality gate: should this watch item's model be trusted enough to
send a live signal?

Prefers *live* out-of-sample numbers (the ``modeling`` accuracy leaderboard,
built from persisted, actual-backfilled predictions). Falls back to the
model's own trailing holdout metrics from its last training run when there
are not enough live predictions yet. A model that clears neither is
suppressed with a reason the operator can see.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class GateResult:
    passed: bool
    reason: str = ""
    stats: dict = field(default_factory=dict)


def _live_stats(model, board=None) -> dict | None:
    from modeling.leaderboard import DEFAULT_WINDOW, build_leaderboard

    if board is None:
        try:
            board = build_leaderboard(window_days=DEFAULT_WINDOW)
        except Exception:  # noqa: BLE001 - the gate must never blow up
            logger.exception("gate: leaderboard build failed")
            return None
    for row in board.ranked:
        if row.model.pk == model.pk and row.n:
            return {
                "source": "leaderboard",
                "window_days": DEFAULT_WINDOW,
                "n": row.n,
                "directional_accuracy": row.directional_accuracy,
                "skill": row.skill,
                "mae": row.mae,
            }
    return None


def _holdout_stats(model) -> dict | None:
    holdout = (model.metrics or {}).get("holdout") or {}
    if not holdout:
        return None
    return {
        "source": "holdout",
        "n": holdout.get("n"),
        "directional_accuracy": holdout.get("directional_accuracy"),
        "skill": holdout.get("skill_vs_naive"),
        "mae": holdout.get("mae"),
    }


def evaluate_gate(item, board=None) -> GateResult:
    """Evaluate ``item``'s model against the accuracy gate. ``board`` is an
    optional, pre-built ``modeling.leaderboard`` result - pass one in when
    evaluating several watch items in the same request/task so the
    leaderboard (itself several queries per active model) is built once
    instead of once per item."""
    model = item.trading_model
    if model is None:
        return GateResult(False, "watch item has no trading model")
    if not model.is_active:
        return GateResult(False, "model is not active")
    if not model.artifact_path:
        return GateResult(False, "model has not been trained yet")

    stats = _live_stats(model, board=board) or _holdout_stats(model)
    if not stats:
        return GateResult(
            False, "no accuracy stats yet - train the model / let predictions accumulate"
        )

    da = stats.get("directional_accuracy")
    skill = stats.get("skill")
    if da is None:
        return GateResult(False, "directional accuracy not computable", stats)
    if da < item.min_directional_accuracy:
        return GateResult(
            False,
            f"directional accuracy {da:.1%} < required {item.min_directional_accuracy:.1%} "
            f"({stats['source']}, n={stats.get('n')})",
            stats,
        )
    if item.min_skill > 0:
        if skill is None:
            return GateResult(False, "skill-vs-naive not computable", stats)
        if skill < item.min_skill:
            return GateResult(False, f"skill {skill:+.3f} < required {item.min_skill:+.3f}", stats)
    return GateResult(True, f"passed ({stats['source']}, n={stats.get('n')})", stats)
