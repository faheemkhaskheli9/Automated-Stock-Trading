from datetime import datetime, timezone

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone as dj_timezone

from marketdata.models import Instrument
from research.providers.news import ingest_feeds
from research.services import get_or_build_snapshot


class Command(BaseCommand):
    help = (
        "Ingest configured news feeds and build point-in-time ResearchSnapshot "
        "feature bundles for active instruments (PSX by default)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--symbol", help="Only this symbol instead of all active instruments.")
        parser.add_argument("--exchange", default="PSX")
        parser.add_argument(
            "--as-of",
            dest="as_of",
            help="Build the snapshot as of this date (YYYY-MM-DD). Default: now.",
        )
        parser.add_argument(
            "--no-news", action="store_true", help="Skip the news-feed ingestion step."
        )
        parser.add_argument(
            "--rebuild", action="store_true", help="Recompute even if a snapshot already exists."
        )

    def handle(self, *args, **options):
        exchange = options["exchange"]
        as_of = _parse_as_of(options.get("as_of"))

        if not options["no_news"]:
            created = ingest_feeds(exchange=exchange)
            self.stdout.write(f"News ingest: {created} new item(s)")

        if options.get("symbol"):
            symbols = [options["symbol"].upper()]
            if not Instrument.objects.filter(exchange=exchange, symbol=symbols[0]).exists():
                raise CommandError(f"No Instrument {symbols[0]!r} on {exchange}.")
        else:
            symbols = list(
                Instrument.objects.filter(exchange=exchange, is_active=True).values_list(
                    "symbol", flat=True
                )
            )

        for symbol in symbols:
            snap = get_or_build_snapshot(
                symbol, as_of, exchange=exchange, rebuild=options["rebuild"]
            )
            self.stdout.write(f"  {symbol}: {len(snap.features)} features @ {as_of:%Y-%m-%d}")

        self.stdout.write(self.style.SUCCESS(f"Built {len(symbols)} snapshot(s)"))


def _parse_as_of(value: str | None) -> datetime:
    if not value:
        return dj_timezone.now().astimezone(timezone.utc)
    return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
