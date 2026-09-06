"""Store a fresh next-session prediction for every active TradingModel.

The batch counterpart to ``predict_model`` (which targets one model). Runs
the same code as ``modeling.tasks.run_model_predictions`` in-process, with
per-instrument failures isolated. Meant to run daily, after ``sync_research``
and before ``backfill_actuals`` - see ``AutomaticStockTrading/schedules.py``
and ``docs/DEPLOYMENT.md``.
"""

from django.core.management.base import BaseCommand

from modeling.tasks import run_model_predictions


class Command(BaseCommand):
    help = "Write next-session ModelPrediction rows for every active TradingModel."

    def handle(self, *args, **options):
        ids = run_model_predictions()
        self.stdout.write(self.style.SUCCESS(f"Wrote {len(ids)} prediction(s)."))
