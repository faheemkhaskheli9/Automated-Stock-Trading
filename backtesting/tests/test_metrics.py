from datetime import date, timedelta

import numpy as np

from backtesting.metrics import (
    combine_equity_curves,
    positions_from_forecast,
    simulate_instrument,
)


def test_positions_close_vs_anchor():
    anchor = np.array([100.0, 100.0, 100.0])
    pred = np.array([101.0, 100.0, 98.0])
    pos = positions_from_forecast("horizon_close", pred, anchor, long_threshold=0.005)
    assert pos.tolist() == [1, 0, 0]
    pos_s = positions_from_forecast(
        "horizon_close", pred, anchor, long_threshold=0.005, allow_short=True
    )
    assert pos_s.tolist() == [1, 0, -1]


def test_positions_return_threshold_and_direction():
    z = np.zeros(3)
    assert positions_from_forecast(
        "horizon_return", np.array([0.02, 0.0, -0.02]), z, long_threshold=0.01, allow_short=True
    ).tolist() == [1, 0, -1]
    assert positions_from_forecast("direction", np.array([1.0, 0.0, 1.0]), z).tolist() == [1, 0, 1]
    assert positions_from_forecast(
        "direction",
        np.array([0, 0, 0]),
        z,
        proba_up=np.array([0.9, 0.5, 0.1]),
        allow_short=True,
    ).tolist() == [1, 0, -1]


def test_simulate_long_then_flat_tracks_price():
    dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(4)]
    closes = np.array([100.0, 110.0, 121.0, 121.0])
    positions = np.array([1, 1, 0, 0])
    curve, trades = simulate_instrument(dates, closes, positions, initial_cash=1_000.0)
    assert curve[-1][1] == abs(1_000.0 * 1.10 * 1.10)  # +10% then +10%
    assert len(trades) == 1
    t = trades[0]
    assert t["direction"] == 1 and t["entry_price"] == 100.0 and t["exit_price"] == 121.0
    assert t["pnl"] > 0 and t["return_pct"] > 0


def test_costs_reduce_equity():
    dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(3)]
    closes = np.array([100.0, 100.0, 100.0])
    positions = np.array([1, 1, 0])
    free, _ = simulate_instrument(dates, closes, positions, initial_cash=1_000.0)
    charged, _ = simulate_instrument(
        dates, closes, positions, initial_cash=1_000.0, commission_bps=50, slippage_bps=50
    )
    assert charged[-1][1] < free[-1][1] == 1_000.0


def test_combine_equity_curves_sums_allocations():
    a = [(date(2024, 1, 1), 50.0), (date(2024, 1, 2), 60.0)]
    b = [(date(2024, 1, 2), 40.0), (date(2024, 1, 3), 30.0)]
    combined = combine_equity_curves([a, b], initial_cash=100.0)
    assert combined[0] == (date(2024, 1, 1), 50.0 + 50.0)  # b still in cash
    assert combined[1] == (date(2024, 1, 2), 60.0 + 40.0)
    assert combined[2] == (date(2024, 1, 3), 60.0 + 30.0)  # a forward-filled
