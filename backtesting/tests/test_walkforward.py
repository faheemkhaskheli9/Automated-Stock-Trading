import random
from datetime import date, timedelta

import pytest

from backtesting.walkforward import EXPANDING, ROLLING, generate_folds


def _sessions(n):
    return [date(2024, 1, 1) + timedelta(days=i) for i in range(n)]


def test_too_short_history_yields_no_folds():
    assert generate_folds(_sessions(30), train_span=250, test_span=21, step=21) == []


def test_expanding_windows_grow_from_the_start():
    s = _sessions(400)
    folds = generate_folds(s, scheme=EXPANDING, train_span=100, test_span=20, step=20, gap=1)
    assert len(folds) >= 3
    assert all(f.train_start == s[0] for f in folds)
    assert folds[1].train_end > folds[0].train_end


def test_rolling_windows_are_fixed_length():
    s = _sessions(400)
    folds = generate_folds(s, scheme=ROLLING, train_span=100, test_span=20, step=20, gap=1)
    for f in folds:
        span = s.index(f.train_end) - s.index(f.train_start)
        assert span == 99  # 100 sessions inclusive


def test_step_advances_test_blocks():
    s = _sessions(400)
    folds = generate_folds(s, train_span=100, test_span=20, step=25, gap=1)
    starts = [s.index(f.test_start) for f in folds]
    assert all(b - a == 25 for a, b in zip(starts, starts[1:]))


@pytest.mark.parametrize("seed", range(20))
def test_train_always_before_test_with_gap(seed):
    rng = random.Random(seed)
    n = rng.randint(150, 600)
    train_span = rng.randint(20, 120)
    test_span = rng.randint(5, 40)
    step = rng.randint(5, 40)
    gap = rng.randint(0, 10)
    s = _sessions(n)
    folds = generate_folds(
        s,
        scheme=rng.choice([EXPANDING, ROLLING]),
        train_span=train_span,
        test_span=test_span,
        step=step,
        gap=gap,
    )
    for f in folds:
        assert f.train_end < f.test_start
        sep = s.index(f.test_start) - s.index(f.train_end)
        assert sep >= gap + 1
        assert s.index(f.test_end) - s.index(f.test_start) == test_span - 1
