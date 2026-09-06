"""Fold generation for walk-forward backtesting - pure, no Django imports.

Given the ordered list of trading-session dates that actually have data,
:func:`generate_folds` yields ``(train, test)`` windows that march forward in
time. Every fold keeps its whole training window strictly before its test
window, with at least ``gap`` sessions of embargo in between, so a fold can
never be scored on a bar it was trained on. ``engine`` adds a second, label-
availability guard on top of this.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

EXPANDING = "expanding"
ROLLING = "rolling"


@dataclass(frozen=True)
class Fold:
    index: int
    train_start: date
    train_end: date
    test_start: date
    test_end: date


def generate_folds(
    sessions: list[date],
    *,
    scheme: str = EXPANDING,
    train_span: int = 250,
    test_span: int = 21,
    step: int = 21,
    gap: int = 1,
) -> list[Fold]:
    """Return the ordered list of folds over ``sessions``.

    ``sessions`` must be sorted ascending and unique. ``train_span`` is the
    minimum training history (rolling: the exact window length). Returns
    ``[]`` when the history is too short for even one fold.
    """
    if scheme not in (EXPANDING, ROLLING):
        raise ValueError(f"unknown scheme {scheme!r}; use {EXPANDING!r} or {ROLLING!r}")
    for name, value in (("train_span", train_span), ("test_span", test_span), ("step", step)):
        if value < 1:
            raise ValueError(f"{name} must be >= 1")
    if gap < 0:
        raise ValueError("gap must be >= 0")

    n = len(sessions)
    folds: list[Fold] = []
    # ``train_hi`` is one-past the last training index; the test block starts
    # ``gap`` sessions later.
    train_hi = train_span
    while True:
        test_lo = train_hi + gap
        test_hi = test_lo + test_span
        if test_hi > n:
            break
        train_lo = 0 if scheme == EXPANDING else max(0, train_hi - train_span)
        fold = Fold(
            index=len(folds),
            train_start=sessions[train_lo],
            train_end=sessions[train_hi - 1],
            test_start=sessions[test_lo],
            test_end=sessions[test_hi - 1],
        )
        # Invariant the whole app relies on.
        assert fold.train_end < fold.test_start, fold
        folds.append(fold)
        train_hi += step
    return folds
