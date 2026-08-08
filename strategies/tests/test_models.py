from django.core.exceptions import ValidationError
from django.test import TestCase

from strategies.models import Strategy
from strategies.rules import MovingAverageCrossoverStrategy


class StrategyModelTests(TestCase):
    def test_clean_accepts_registered_key(self):
        strategy = Strategy(name="My MA", key="ma_crossover")
        strategy.clean()  # should not raise

    def test_clean_rejects_unknown_key(self):
        strategy = Strategy(name="Bogus", key="does_not_exist")
        with self.assertRaises(ValidationError):
            strategy.clean()

    def test_build_instantiates_configured_class(self):
        strategy = Strategy(
            name="My MA", key="ma_crossover", params={"fast_period": 5, "slow_period": 20}
        )
        instance = strategy.build()

        self.assertIsInstance(instance, MovingAverageCrossoverStrategy)
        self.assertEqual(instance.fast_period, 5)
        self.assertEqual(instance.slow_period, 20)

    def test_str(self):
        strategy = Strategy(name="My MA", key="ma_crossover")
        self.assertEqual(str(strategy), "My MA (ma_crossover)")
