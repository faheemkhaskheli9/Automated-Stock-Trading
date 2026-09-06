from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase


class RunModelPredictionsCommandTests(TestCase):
    @patch("modeling.management.commands.run_model_predictions.run_model_predictions")
    def test_reports_count(self, mock_run):
        mock_run.return_value = [1, 2, 3]
        out = StringIO()

        call_command("run_model_predictions", stdout=out)

        mock_run.assert_called_once_with()
        self.assertIn("Wrote 3 prediction(s).", out.getvalue())

    def test_no_active_models_is_a_clean_noop(self):
        out = StringIO()
        call_command("run_model_predictions", stdout=out)
        self.assertIn("Wrote 0 prediction(s).", out.getvalue())
