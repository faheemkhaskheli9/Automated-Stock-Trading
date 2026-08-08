from django.test import SimpleTestCase

from strategies.ml import MLModelStrategy
from strategies.signals import Action

from .factories import make_bars


class MLModelStrategyTests(SimpleTestCase):
    def test_no_model_configured_holds(self):
        strategy = MLModelStrategy()
        bars = make_bars([10, 11, 12])
        signals = strategy.generate_signals(bars)
        self.assertTrue(all(s.action == Action.HOLD for s in signals))
        self.assertEqual(signals[0].reason, "no model configured")

    def test_missing_model_file_holds(self):
        strategy = MLModelStrategy(model_path="/does/not/exist.joblib")
        bars = make_bars([10, 11])
        signals = strategy.generate_signals(bars)
        self.assertTrue(all(s.action == Action.HOLD for s in signals))

    def test_loaded_model_drives_predictions(self):
        class StubModel:
            def predict(self, features):
                return [1]  # always BUY

        strategy = MLModelStrategy(lookback=2)
        strategy._model = StubModel()  # bypass file loading for the unit test
        bars = make_bars([10, 11, 12])

        signals = strategy.generate_signals(bars)

        self.assertEqual(signals[0].action, Action.HOLD)  # insufficient history (lookback=2)
        self.assertEqual(signals[1].action, Action.BUY)
        self.assertEqual(signals[2].action, Action.BUY)
