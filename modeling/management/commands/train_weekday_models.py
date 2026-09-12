from django.core.management.base import BaseCommand, CommandError
from django.utils.dateparse import parse_date

from marketdata.models import Instrument
from modeling import symbol_selection
from modeling.weekday_suite import build_weekday_suite, suite_estimator_keys


class Command(BaseCommand):
    help = (
        "Train one TradingModel per available regression estimator on the "
        "Monday->Friday (weekday_anchored) target for one instrument, then "
        "print a holdout-accuracy comparison. Auto-picks the best-covered "
        "active instrument if --symbol is omitted."
    )

    def add_arguments(self, parser):
        parser.add_argument("--symbol", help="Instrument symbol to train on (default: auto-pick).")
        parser.add_argument("--exchange", default="PSX")
        parser.add_argument(
            "--estimators",
            help=f"Comma-separated estimator keys (default: all of {suite_estimator_keys()}).",
        )
        parser.add_argument("--start", help="Train window start, YYYY-MM-DD.")
        parser.add_argument("--end", help="Train window end, YYYY-MM-DD.")
        parser.add_argument("--holdout-fraction", type=float, default=0.2)
        parser.add_argument(
            "--rank-symbols",
            action="store_true",
            help="Just print the instrument ranking used for auto-pick and exit.",
        )

    def handle(self, *args, **options):
        if options["rank_symbols"]:
            self._print_ranking()
            return

        instrument = None
        if options["symbol"]:
            try:
                instrument = Instrument.objects.get(
                    symbol=options["symbol"], exchange=options["exchange"]
                )
            except Instrument.DoesNotExist as exc:
                raise CommandError(
                    f"No instrument {options['symbol']!r} on {options['exchange']!r}."
                ) from exc

        estimators = None
        if options["estimators"]:
            estimators = [k.strip() for k in options["estimators"].split(",") if k.strip()]

        start = parse_date(options["start"]) if options["start"] else None
        end = parse_date(options["end"]) if options["end"] else None

        result = build_weekday_suite(
            instrument,
            estimators=estimators,
            train_start=start,
            train_end=end,
            holdout_fraction=options["holdout_fraction"],
        )

        for err in result.errors:
            self.stderr.write(self.style.WARNING(err))

        if not result.models:
            self.stdout.write(self.style.WARNING("No models were trained."))
            return

        self.stdout.write(
            f"Trained {len(result.models)} model(s) on "
            f"{result.instrument.symbol} ({result.instrument.exchange}):\n"
        )
        header = (
            f"{'rank':>4}  {'estimator':<20}{'status':<10}{'mae':>10}{'dir.acc':>10}{'skill':>10}"
        )
        self.stdout.write(header)
        for row in result.evaluation:
            self.stdout.write(
                f"{row['rank']:>4}  {row['estimator']:<20}{row['status']:<10}"
                f"{self._fmt(row['mae']):>10}{self._fmt(row['directional_accuracy']):>10}"
                f"{self._fmt(row['skill_vs_naive']):>10}"
            )

    def _print_ranking(self):
        scores = symbol_selection.score_instruments()
        if not scores:
            self.stdout.write(self.style.WARNING("No active instrument has any price history."))
            return
        self.stdout.write(
            f"{'symbol':<10}{'viable':<8}{'pairs':>7}{'coverage':>10}{'score':>8}  reasons"
        )
        for s in scores:
            reasons = "; ".join(s.reasons)
            self.stdout.write(
                f"{s.instrument.symbol:<10}{str(s.viable):<8}{s.weekday_pairs:>7}"
                f"{s.coverage:>10.2f}{s.score:>8.3f}  {reasons}"
            )

    @staticmethod
    def _fmt(value) -> str:
        return "n/a" if value is None else f"{value:.4f}"
