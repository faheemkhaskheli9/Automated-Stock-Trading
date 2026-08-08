from django.test import SimpleTestCase

from strategies.registry import get_strategy_class, registered_keys, registry_choices


class RegistryTests(SimpleTestCase):
    """Uses the app's real registrations (populated via StrategiesConfig.ready()
    importing rules/manual/ml) rather than registering throwaway test classes,
    since the registry is process-global module state."""

    def test_reference_strategies_are_registered(self):
        self.assertIn("ma_crossover", registered_keys())
        self.assertIn("rsi", registered_keys())
        self.assertIn("manual", registered_keys())
        self.assertIn("ml_model", registered_keys())

    def test_get_unknown_key_raises(self):
        with self.assertRaises(KeyError):
            get_strategy_class("does_not_exist")

    def test_registry_choices_shape(self):
        choices = dict(registry_choices())
        self.assertEqual(choices["ma_crossover"], "Moving Average Crossover")
