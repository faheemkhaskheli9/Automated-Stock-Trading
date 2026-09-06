from datetime import date

from django.core.management.base import BaseCommand

from signalfeed.services import recap_weekly_signals


class Command(BaseCommand):
    help = "Backfill actual closes onto past weekly signals, grade them, and send a recap."

    def add_arguments(self, parser):
        parser.add_argument("--as-of", type=date.fromisoformat, default=None)
        parser.add_argument("--window-days", type=int, default=90)
        parser.add_argument(
            "--no-deliver", action="store_true", help="Grade only; do not send the recap."
        )

    def handle(self, *args, **opts):
        summary = recap_weekly_signals(
            opts["as_of"],
            window_days=opts["window_days"],
            deliver_recap=not opts["no_deliver"],
        )
        rate = summary["window_hit_rate"]
        self.stdout.write(
            self.style.SUCCESS(
                "scored_now={scored_now} week={week_hits}/{week_total} "
                "window={window_hits}/{window_total} ".format(**summary)
                + (f"({rate:.0%})" if rate is not None else "")
                + f" delivered_to={summary['delivered_to']}"
            )
        )
