"""Unit tests for the pure position-sizing helper (no DB)."""

import pytest

from signalfeed.sizing import suggest_size


def _size(**kw):
    base = dict(
        direction="up",
        directional_accuracy=0.60,
        capital=100_000.0,
        max_position_pct=10.0,
        kelly_fraction=0.5,
        reference_close=50.0,
    )
    base.update(kw)
    return suggest_size(**base)


def test_disabled_when_no_capital():
    assert _size(capital=0) is None
    assert _size(capital=-5) is None


def test_none_for_non_actionable_direction():
    assert _size(direction="flat") is None


def test_edge_scales_below_the_cap():
    # acc 0.55 -> edge 0.10 -> half-Kelly 0.05, under the 10% cap.
    s = _size(directional_accuracy=0.55)
    assert s.fraction == pytest.approx(0.05)
    assert s.notional == pytest.approx(5_000.0)
    assert s.shares == 100  # floor(5000 / 50)


def test_cap_clamps_a_strong_edge():
    # acc 1.0 -> edge 1.0 -> half-Kelly 0.5, clamped to max_position_pct/100.
    s = _size(directional_accuracy=1.0)
    assert s.fraction == pytest.approx(0.10)
    assert s.notional == pytest.approx(10_000.0)
    assert s.shares == 200


def test_coin_flip_model_sizes_to_zero():
    s = _size(directional_accuracy=0.50)
    assert s.fraction == 0.0
    assert s.notional == 0.0
    assert s.shares == 0


def test_kelly_fraction_zero_sizes_flat_at_cap():
    s = _size(kelly_fraction=0, directional_accuracy=0.52)
    assert s.fraction == pytest.approx(0.10)  # ignores the (tiny) edge


def test_missing_accuracy_treated_as_coin_flip():
    s = _size(directional_accuracy=None)
    assert s.fraction == 0.0


def test_shares_zero_without_a_reference_close():
    s = _size(reference_close=None)
    assert s.shares == 0
    assert s.notional > 0  # notional is still meaningful


def test_basis_snapshots_every_input():
    s = _size(directional_accuracy=0.6)
    assert s.basis == {
        "capital": 100_000.0,
        "max_position_pct": 10.0,
        "kelly_fraction": 0.5,
        "directional_accuracy": 0.6,
        "edge": 0.2,
        "reference_close": 50.0,
    }
