from django.core.management.base import BaseCommand

from signalfeed.services import train_weekly_models


class Command(BaseCommand):
    help = "Retrain every model referenced by an active watch item."

    def add_arguments(self, parser):
        parser.add_argument(
            "--model-id", type=int, default=None, help="Restrict to one TradingModel id."
        )

    def handle(self, *args, **opts):
        runs = train_weekly_models(model_id=opts["model_id"])
        if not runs:
            self.stdout.write("No models to train (no active watch items?).")
            return
        for run in runs:
            style = self.style.SUCCESS if run.status == run.Status.SUCCESS else self.style.ERROR
            self.stdout.write(
                style(
                    f"  {run.model.name}: {run.status} "
                    + (run.error or f"rows={run.rows} features={run.feature_count}")
                )
            )
