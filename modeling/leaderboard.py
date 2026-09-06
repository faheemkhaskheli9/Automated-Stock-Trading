"""Accuracy leaderboard for active :class:`~modeling.models.TradingModel` s.

Ranks every active model by how its persisted, actual-backfilled
``ModelPrediction`` rows turned out over a trailing window, so the operator
can see which configured models are actually earning their keep.

Three numbers per model, all out-of-sample (only predictions whose target
session has closed and been backfilled count):

``mae``
    Mean absolute error, in the target's own units (price for close targets,
    fraction for return targets, ``None`` for the ``direction`` classifier).
``directional_accuracy``
    Share of predictions that called the move (up vs down) correctly relative
    to the last close known when the forecast was made. For ``direction``
    models this is just plain accuracy.
``skill``
    Improvement over the naive "no change" forecast:
    ``1 - model_mae / naive_mae`` for regression targets (``> 0`` beats
    persistence), and ``(accuracy - majority_rate) / (1 - majority_rate)`` for
    the classifier (``> 0`` beats always guessing the majority class).

Ranking is by ``skill`` (models without a computable skill score sort last),
tie-broken by ``directional_accuracy`` - MAE is shown but never used to rank,
since it is not comparable across targets on different scales.
"""

from __future__ import annotations

import bisect
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta

from django.utils import timezone

from marketdata.models import PriceBar

from . import targets as target_mod
from .models import ModelPrediction, TradingModel

logger = logging.getLogger(__name__)

WINDOW_CHOICES = (30, 90, 180, 365)
DEFAULT_WINDOW = 90


@dataclass
class LeaderboardRow:
    model: TradingModel
    task: str
    target_type: str
    n: int
    mae: float | None = None
    directional_accuracy: float | None = None
    skill: float | None = None
    last_target_date: date | None = None
    rank: int = 0


@dataclass
class Leaderboard:
    window_days: int
    cutoff: date
    as_of: date
    ranked: list[LeaderboardRow] = field(default_factory=list)
    unscored: list[TradingModel] = field(default_factory=list)


def _sign(value: float) -> int:
    return (value > 0) - (value < 0)


def _base_closes(predictions: list[ModelPrediction]) -> dict[int, float]:
    """Map each prediction pk to the last daily close on/before its ``as_of``.

    One query for every instrument involved, then a bisect per prediction -
    no per-row database hit.
    """
    instrument_ids = {p.instrument_id for p in predictions}
    if not instrument_ids:
        return {}

    series: dict[int, tuple[list, list]] = {}
    rows = (
        PriceBar.objects.filter(
            instrument_id__in=instrument_ids, timeframe=PriceBar.Timeframe.DAILY
        )
        .order_by("instrument_id", "timestamp")
        .values_list("instrument_id", "timestamp", "close")
    )
    for instrument_id, ts, close in rows:
        stamps, closes = series.setdefault(instrument_id, ([], []))
        stamps.append(ts)
        closes.append(float(close))

    out: dict[int, float] = {}
    for pred in predictions:
        stamps, closes = series.get(pred.instrument_id, ([], []))
        idx = bisect.bisect_right(stamps, pred.as_of) - 1
        if idx >= 0:
            out[pred.pk] = closes[idx]
    return out


def _score(model: TradingModel, predictions: list[ModelPrediction]) -> LeaderboardRow:
    try:
        ttype = target_mod.validate_spec(model.target_spec)["type"]
    except ValueError:
        ttype = (
            str(model.target_spec.get("type", "?")) if isinstance(model.target_spec, dict) else "?"
        )
    task = "classification" if ttype == "direction" else "regression"
    row = LeaderboardRow(
        model=model,
        task=task,
        target_type=ttype,
        n=len(predictions),
        last_target_date=max(p.target_date for p in predictions),
    )

    errors = [p.abs_error for p in predictions if p.abs_error is not None]

    if ttype == "direction":
        if errors:
            accuracy = sum(1.0 - e for e in errors) / len(errors)
            row.directional_accuracy = accuracy
            positive_rate = sum(p.actual_value for p in predictions) / len(predictions)
            majority = max(positive_rate, 1.0 - positive_rate)
            row.skill = (accuracy - majority) / (1.0 - majority) if majority < 1.0 else None
        return row

    if errors:
        row.mae = sum(errors) / len(errors)

    if ttype == "horizon_return":
        deltas = [(p.predicted_value, p.actual_value) for p in predictions]
    else:  # price target - measure the move against the pre-forecast close
        bases = _base_closes(predictions)
        deltas = [
            (p.predicted_value - bases[p.pk], p.actual_value - bases[p.pk])
            for p in predictions
            if p.pk in bases
        ]

    if deltas:
        row.directional_accuracy = sum(
            _sign(pred_d) == _sign(actual_d) for pred_d, actual_d in deltas
        ) / len(deltas)
        naive_mae = sum(abs(actual_d) for _, actual_d in deltas) / len(deltas)
        if row.mae is not None and naive_mae:
            row.skill = 1.0 - row.mae / naive_mae

    return row


def build_leaderboard(
    *, window_days: int = DEFAULT_WINDOW, as_of: date | None = None
) -> Leaderboard:
    """Score every active model over the trailing ``window_days`` and rank."""
    if window_days not in WINDOW_CHOICES:
        window_days = DEFAULT_WINDOW
    as_of = as_of or timezone.localdate()
    cutoff = as_of - timedelta(days=window_days)
    board = Leaderboard(window_days=window_days, cutoff=cutoff, as_of=as_of)

    models = (
        TradingModel.objects.filter(is_active=True).prefetch_related("instruments").order_by("name")
    )
    for model in models:
        predictions = list(
            ModelPrediction.objects.filter(
                model=model,
                actual_value__isnull=False,
                predicted_value__isnull=False,
                target_date__gte=cutoff,
                target_date__lt=as_of,
            )
            .select_related("instrument")
            .order_by("target_date")
        )
        if not predictions:
            board.unscored.append(model)
            continue
        try:
            board.ranked.append(_score(model, predictions))
        except Exception:  # noqa: BLE001 - a leaderboard row must never 500 the page
            logger.exception("leaderboard scoring failed for model %s", model.pk)
            board.unscored.append(model)

    board.ranked.sort(
        key=lambda r: (
            r.skill if r.skill is not None else float("-inf"),
            r.directional_accuracy if r.directional_accuracy is not None else float("-inf"),
        ),
        reverse=True,
    )
    for i, row in enumerate(board.ranked, start=1):
        row.rank = i
    return board
