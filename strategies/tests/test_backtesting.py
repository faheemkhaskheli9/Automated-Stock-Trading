from django.test import SimpleTestCase

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
