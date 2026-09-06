from django.core.management.base import BaseCommand, CommandError

from modeling.models import TradingModel
from modeling.services import backfill_actuals


class Command(BaseCommand):
    help = "Fill actual_value / abs_error on stored predictions whose target session has passed."

    def add_arguments(self, parser):
        parser.add_argument("--model", type=int, default=None, help="Limit to one TradingModel id.")

    def handle(self, *args, **opts):
        model = None
        if opts["model"] is not None:
            try:
                model = TradingModel.objects.get(pk=opts["model"])
            except TradingModel.DoesNotExist as exc:
                raise CommandError(str(exc)) from exc
        filled = backfill_actuals(model)
        self.stdout.write(self.style.SUCCESS(f"Backfilled {filled} prediction(s)."))
