from datetime import date

from django.core.management.base import BaseCommand, CommandError

from modeling.models import TradingModel
from modeling.services import train_model


class Command(BaseCommand):
    help = "Train a configured TradingModel and write its joblib artifact."

    def add_arguments(self, parser):
        parser.add_argument("model_id", type=int)
        parser.add_argument("--start", type=date.fromisoformat, default=None)
        parser.add_argument("--end", type=date.fromisoformat, default=None)

    def handle(self, *args, **opts):
        try:
            model = TradingModel.objects.get(pk=opts["model_id"])
        except TradingModel.DoesNotExist as exc:
            raise CommandError(f"No TradingModel with id {opts['model_id']}") from exc

        run = train_model(model, start=opts["start"], end=opts["end"])
        if run.status != run.Status.SUCCESS:
            raise CommandError(f"Training failed: {run.error}")
        self.stdout.write(
            self.style.SUCCESS(
                f"Trained model {model.pk} on {run.rows} rows / {run.feature_count} features. "
                f"Artifact: {run.artifact_path}"
            )
        )
        self.stdout.write(f"Holdout metrics: {run.metrics.get('holdout')}")
