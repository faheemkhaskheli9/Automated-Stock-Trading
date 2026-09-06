from datetime import date

from django.core.management.base import BaseCommand, CommandError

from backtesting.models import Backtest
from backtesting.services import run_backtest
from modeling.models import ModelTrainingRun


class Command(BaseCommand):
    help = (
        "Run a backtest of a configured Backtest row. Pass any of the window / mode "
        "flags to override the stored config for this run only."
    )

    def add_arguments(self, parser):
        parser.add_argument("backtest_id", type=int)
        parser.add_argument("--fit-mode", choices=[m.value for m in Backtest.FitMode], default=None)
        parser.add_argument(
            "--training-run",
            type=int,
            default=None,
            help="frozen_artifact: ModelTrainingRun id whose artifact to score.",
        )
        parser.add_argument("--scheme", choices=[s.value for s in Backtest.Scheme], default=None)
        parser.add_argument("--train-span", type=int, default=None)
        parser.add_argument("--test-span", type=int, default=None)
        parser.add_argument("--step", type=int, default=None)
        parser.add_argument("--gap", type=int, default=None)
        parser.add_argument("--start", type=date.fromisoformat, default=None)
        parser.add_argument("--end", type=date.fromisoformat, default=None)

    def handle(self, *args, **opts):
        try:
            backtest = Backtest.objects.get(pk=opts["backtest_id"])
        except Backtest.DoesNotExist as exc:
            raise CommandError(f"No Backtest with id {opts['backtest_id']}") from exc

        if opts["training_run"] is not None:
            try:
                backtest.training_run = ModelTrainingRun.objects.get(pk=opts["training_run"])
            except ModelTrainingRun.DoesNotExist as exc:
                raise CommandError(f"No ModelTrainingRun with id {opts['training_run']}") from exc

        overrides = {
            "fit_mode": opts["fit_mode"],
            "scheme": opts["scheme"],
            "train_span": opts["train_span"],
            "test_span": opts["test_span"],
            "step": opts["step"],
            "gap": opts["gap"],
            "start": opts["start"],
            "end": opts["end"],
        }
        for field, value in overrides.items():
            if value is not None:
                setattr(backtest, field, value)

        run = run_backtest(backtest)
        if run.status != run.Status.SUCCESS:
            raise CommandError(f"Backtest failed: {run.error}")
        self.stdout.write(
            self.style.SUCCESS(
                f"Backtest {backtest.pk}: {run.n_folds} folds, {run.n_predictions} predictions, "
                f"{run.n_trades} trades."
            )
        )
        self.stdout.write(f"Accuracy: {run.metrics.get('accuracy')}")
        self.stdout.write(f"Trading:  {run.metrics.get('trading')}")
