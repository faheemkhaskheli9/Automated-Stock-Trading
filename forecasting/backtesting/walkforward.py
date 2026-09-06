"""Fold generation for walk-forward backtesting - pure, no Django imports.

The assembled training frame has exactly one row per completed decision
session, already time-ordered. So a fold is just a pair of contiguous row-
position windows over that frame. Every fold keeps its whole training window
strictly before its test window, with at least ``gap`` sessions of embargo in
between, so a predictor can never be scored on a bar it was trained on.
``engine`` layers a second, label-availability guard on top of this.
"""

from __future__ import annotations

from dataclasses import dataclass

EXPANDING = "expanding"
ROLLING = "rolling"


@dataclass(frozen=True)
class Fold:
    index: int
    train: range
    test: range

    def __post_init__(self):
        if not (len(self.train) and len(self.test)):
            raise ValueError("a fold needs a non-empty train and test window")
        # The invariant the whole harness relies on.
        assert self.train.stop - 1 < self.test.start, self


def generate_folds(
    n_rows: int,
    *,
    scheme: str = EXPANDING,
    train_span: int = 250,
    test_span: int = 21,
    step: int = 21,
    gap: int = 1,
) -> list[Fold]:
    """Return the ordered list of folds over ``n_rows`` decision rows.

    ``train_span`` is the minimum training history (rolling: the exact window
    length). ``gap`` sessions are held out between the last training row and
    the first test row. Returns ``[]`` when the history is too short for even
    one fold.
    """
    if scheme not in (EXPANDING, ROLLING):
        raise ValueError(f"unknown scheme {scheme!r}; use {EXPANDING!r} or {ROLLING!r}")
    for name, value in (("train_span", train_span), ("test_span", test_span), ("step", step)):
        if value < 1:
            raise ValueError(f"{name} must be >= 1")
    if gap < 0:
        raise ValueError("gap must be >= 0")

    folds: list[Fold] = []
    train_hi = train_span  # one past the last training row
    while True:
        test_lo = train_hi + gap
        test_hi = test_lo + test_span
        if test_hi > n_rows:
            break
        train_lo = 0 if scheme == EXPANDING else max(0, train_hi - train_span)
        folds.append(
            Fold(
                index=len(folds),
                train=range(train_lo, train_hi),
                test=range(test_lo, test_hi),
            )
        )
        train_hi += step
    return folds
