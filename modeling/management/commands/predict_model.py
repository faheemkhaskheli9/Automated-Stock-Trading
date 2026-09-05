from datetime import date

from django.core.management.base import BaseCommand, CommandError

from marketdata.models import Instrument
from modeling.models import TradingModel
from modeling.services import predict


class Command(BaseCommand):
    help = "Run a trained TradingModel for one symbol and store the prediction."

    def add_arguments(self, parser):
        parser.add_argument("model_id", type=int)
        parser.add_argument("symbol")
        parser.add_argument("--as-of", type=date.fromisoformat, required=True)
        parser.add_argument("--target-date", type=date.fromisoformat, default=None)
        parser.add_argument("--exchange", default="PSX")

    def handle(self, *args, **opts):
        try:
            model = TradingModel.objects.get(pk=opts["model_id"])
            instrument = Instrument.objects.get(symbol=opts["symbol"], exchange=opts["exchange"])
        except (TradingModel.DoesNotExist, Instrument.DoesNotExist) as exc:
            raise CommandError(str(exc)) from exc

        try:
            pred = predict(model, instrument, opts["as_of"], target_date=opts["target_date"])
        except Exception as exc:  # noqa: BLE001
            raise CommandError(f"Prediction failed: {exc}") from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"{instrument.symbol} target {pred.target_date}: "
                f"predicted {pred.predicted_value} (json={pred.predicted_json})"
            )
        )
