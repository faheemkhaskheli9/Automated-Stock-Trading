from datetime import datetime, timedelta, timezone

from django.test import SimpleTestCase

from marketdata.providers.base import Bar
from strategies.backtesting.engine import run_backtest
from strategies.base import BaseStrategy
from strategies.signals import Action, Signal

from .factories import make_bars


class ScriptedStrategy(BaseStrategy):
    """Test double: returns exactly the actions it's given, one per bar."""

    def __init__(self, actions: list[Action]):
        super().__init__()
        self.actions = actions

    def generate_signals(self, bars):
        return [Signal(bar.timestamp, action) for bar, action in zip(bars, self.actions)]


class RunBacktestTests(SimpleTestCase):
    def test_no_bars_returns_flat_result(self):
        result = run_backtest(ScriptedStrategy([]), [], initial_cash=1000)
        self.assertEqual(result.final_equity, 1000)
        self.assertEqual(result.num_trades, 0)

    def test_mismatched_signal_count_raises(self):
        class BrokenStrategy(BaseStrategy):
            def generate_signals(self, bars):
                return []  # wrong length on purpose

        with self.assertRaises(ValueError):
            run_backtest(BrokenStrategy(), make_bars([10, 11]))

    def test_all_hold_leaves_cash_untouched(self):
        bars = make_bars([10, 11, 12])
        result = run_backtest(ScriptedStrategy([Action.HOLD] * 3), bars, initial_cash=1000)

        self.assertEqual(result.final_equity, 1000)
        self.assertEqual(result.num_trades, 0)
        self.assertIsNone(result.win_rate)
        self.assertEqual(result.max_drawdown, 0.0)

    def test_buy_then_sell_realizes_a_trade(self):
        bars = make_bars([100, 100, 150])  # buy at 100, sell at 150 -> profit
        result = run_backtest(
            ScriptedStrategy([Action.BUY, Action.HOLD, Action.SELL]), bars, initial_cash=1000
        )

        self.assertEqual(result.num_trades, 1)
        trade = result.trades[0]
        self.assertEqual(trade.entry_price, 100)
        self.assertEqual(trade.exit_price, 150)
        self.assertEqual(trade.shares, 10)  # 1000 // 100
        self.assertEqual(trade.pnl, 500)  # (150-100)*10
        self.assertEqual(result.win_rate, 1.0)
        self.assertGreater(result.final_equity, result.initial_cash)
        self.assertEqual(result.open_position_shares, 0)

    def test_buy_never_sold_leaves_open_position(self):
        bars = make_bars([100, 110])
        result = run_backtest(ScriptedStrategy([Action.BUY, Action.HOLD]), bars, initial_cash=1000)

        self.assertEqual(result.num_trades, 0)
        self.assertGreater(result.open_position_shares, 0)
        # Equity should reflect the mark-to-market value of the open position.
        self.assertEqual(result.final_equity, 0 + result.open_position_shares * 110)

    def test_max_drawdown_reflects_a_losing_trade(self):
        bars = make_bars([100, 50, 50])  # buy at 100, price crashes to 50
        result = run_backtest(
            ScriptedStrategy([Action.BUY, Action.HOLD, Action.SELL]), bars, initial_cash=1000
        )

        self.assertGreater(result.max_drawdown, 0.0)
        self.assertEqual(result.win_rate, 0.0)


class RunBacktestGuardTests(SimpleTestCase):
    def test_non_positive_initial_cash_raises(self):
        with self.assertRaises(ValueError):
            run_backtest(ScriptedStrategy([]), [], initial_cash=0)

    def test_out_of_range_costs_raise(self):
        bars = make_bars([10, 11])
        with self.assertRaises(ValueError):
            run_backtest(ScriptedStrategy([Action.HOLD] * 2), bars, commission_bps=10_000)
        with self.assertRaises(ValueError):
            run_backtest(ScriptedStrategy([Action.HOLD] * 2), bars, slippage_bps=-1)

    def test_non_positive_price_raises(self):
        bars = [
            Bar(datetime(2026, 1, 1, tzinfo=timezone.utc), 10, 10, 10, 10, 1000),
            Bar(datetime(2026, 1, 2, tzinfo=timezone.utc), 0, 0, 0, 0, 1000),
        ]
        with self.assertRaises(ValueError):
            run_backtest(ScriptedStrategy([Action.HOLD] * 2), bars)

    def test_non_increasing_timestamps_raise(self):
        ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
        bars = [
            Bar(ts, 10, 10, 10, 10, 1000),
            Bar(ts, 11, 11, 11, 11, 1000),  # duplicate timestamp
        ]
        with self.assertRaises(ValueError):
            run_backtest(ScriptedStrategy([Action.HOLD] * 2), bars)


class RunBacktestCostAndTimingTests(SimpleTestCase):
    def _ohlc_bars(self, rows):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        return [
            Bar(start + timedelta(days=i), o, max(o, c), min(o, c), c, 1000)
            for i, (o, c) in enumerate(rows)
        ]

    def test_commission_and_slippage_reduce_realized_pnl(self):
        bars = make_bars([100, 100, 150])
        actions = [Action.BUY, Action.HOLD, Action.SELL]

        clean = run_backtest(ScriptedStrategy(actions), bars, initial_cash=1000)
        costed = run_backtest(
            ScriptedStrategy(actions),
            bars,
            initial_cash=1000,
            commission_bps=25,
            slippage_bps=25,
        )

        self.assertLess(costed.final_equity, clean.final_equity)
        self.assertGreater(costed.trades[0].fees, 0.0)
        # pnl is net of fees
        gross = (costed.trades[0].exit_price - costed.trades[0].entry_price) * costed.trades[
            0
        ].shares
        self.assertAlmostEqual(costed.trades[0].pnl, gross - costed.trades[0].fees)

    def test_next_open_fills_on_the_following_bar_open(self):
        # close on bar 0 says BUY; fill happens at bar 1's open (120), not bar 0 close.
        bars = self._ohlc_bars([(100, 100), (120, 130), (140, 150)])
        result = run_backtest(
            ScriptedStrategy([Action.BUY, Action.SELL, Action.HOLD]),
            bars,
            initial_cash=1000,
            next_open=True,
        )

        self.assertEqual(result.num_trades, 1)
        self.assertEqual(result.trades[0].entry_price, 120)  # bar 1 open (BUY seen on bar 0)
        self.assertEqual(result.trades[0].exit_price, 140)  # bar 2 open (SELL seen on bar 1)

    def test_next_open_ignores_a_final_bar_signal(self):
        # SELL only appears on the last bar - with next_open there is no bar to fill it.
        bars = self._ohlc_bars([(100, 100), (110, 110), (120, 120)])
        result = run_backtest(
            ScriptedStrategy([Action.BUY, Action.HOLD, Action.SELL]),
            bars,
            initial_cash=1000,
            next_open=True,
        )
        self.assertEqual(result.num_trades, 0)
        self.assertGreater(result.open_position_shares, 0)
