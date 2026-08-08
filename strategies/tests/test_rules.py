from django.test import SimpleTestCase

from strategies.rules import MovingAverageCrossoverStrategy, RSIStrategy
from strategies.signals import Action

from .factories import make_bars


class MovingAverageCrossoverStrategyTests(SimpleTestCase):
    def test_insufficient_history_holds(self):
        strategy = MovingAverageCrossoverStrategy(fast_period=2, slow_period=5)
        bars = make_bars([10, 10, 10])

        signals = strategy.generate_signals(bars)

        self.assertEqual(len(signals), 3)
        self.assertTrue(all(s.action == Action.HOLD for s in signals))

    def test_uptrend_then_downtrend_produces_buy_then_sell(self):
        strategy = MovingAverageCrossoverStrategy(fast_period=2, slow_period=3)
        closes = [10, 10, 10, 20, 20, 20, 20, 5, 5, 5, 5]
        bars = make_bars(closes)

        signals = strategy.generate_signals(bars)

        self.assertEqual(len(signals), len(bars))
        actions = [s.action for s in signals]
        self.assertIn(Action.BUY, actions)
        self.assertIn(Action.SELL, actions)
        # The BUY (fast crosses above slow, as price jumps up) must come
        # before the SELL (fast crosses below slow, as price crashes).
        self.assertLess(actions.index(Action.BUY), actions.index(Action.SELL))

    def test_signals_returned_one_per_bar(self):
        strategy = MovingAverageCrossoverStrategy(fast_period=2, slow_period=3)
        bars = make_bars([10, 11, 12, 13, 14, 15, 16, 17])
        signals = strategy.generate_signals(bars)
        self.assertEqual(len(signals), len(bars))
        for bar, signal in zip(bars, signals):
            self.assertEqual(bar.timestamp, signal.timestamp)


class RSIStrategyTests(SimpleTestCase):
    def test_insufficient_history_holds(self):
        strategy = RSIStrategy(period=14)
        bars = make_bars([10, 11, 12])
        signals = strategy.generate_signals(bars)
        self.assertTrue(all(s.action == Action.HOLD for s in signals))

    def test_downtrend_then_uptrend_produces_buy_then_sell(self):
        strategy = RSIStrategy(period=3, oversold=30, overbought=70)
        down = [20 - i for i in range(10)]  # steady decline -> RSI trends toward 0
        up = [d + i for i, d in enumerate([down[-1]] * 10)]  # steady rise -> RSI trends toward 100
        bars = make_bars(down + up)

        signals = strategy.generate_signals(bars)
        actions = [s.action for s in signals]

        self.assertIn(Action.BUY, actions)
        self.assertIn(Action.SELL, actions)
        self.assertLess(actions.index(Action.BUY), actions.index(Action.SELL))
