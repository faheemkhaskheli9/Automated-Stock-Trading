from datetime import date

from django.core.management.base import BaseCommand

from signalfeed.services import send_weekly_signals


class Command(BaseCommand):
    help = "Generate this week's weekly signals for the watchlist and deliver them."

    def add_arguments(self, parser):
        parser.add_argument(
            "--as-of",
            type=date.fromisoformat,
            default=None,
            help="Any date in the target week (default: today). The Monday is derived.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Build and store signals but do not send anything.",
        )
        parser.add_argument(
            "--include-flat",
            action="store_true",
            help="Also deliver FLAT (below-threshold) calls.",
        )
        parser.add_argument(
            "--channel",
            action="append",
            dest="channels",
            choices=["email", "webhook", "telegram"],
            help="Restrict delivery to this channel (repeatable).",
        )

    def handle(self, *args, **opts):
        summary = send_weekly_signals(
            opts["as_of"],
            dry_run=opts["dry_run"],
            include_flat=opts["include_flat"],
            channels=opts["channels"],
        )
        for sig in summary["signals"]:
            self.stdout.write(
                f"  {sig.instrument.symbol:<10} {sig.direction.upper():<5} "
                f"{'' if sig.expected_return_pct is None else format(sig.expected_return_pct, '+.2f') + '%':<8} "
                f"[{sig.status}] {sig.suppression_reason}"
            )
        self.stdout.write(
            self.style.SUCCESS(
                "generated={generated} sent={sent} suppressed={suppressed} "
                "flat={flat} errors={errors}".format(**summary)
            )
        )
