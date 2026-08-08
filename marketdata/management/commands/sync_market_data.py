from datetime import date, datetime

from django.core.management.base import BaseCommand, CommandError

from marketdata.models import Instrument
from marketdata.services import sync_active_instruments, sync_instrument_history


class Command(BaseCommand):
    help = (
        "Backfill/update PriceBar history for active instruments from the "
        "configured market data provider (PSX by default)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--symbol",
            help="Sync a single instrument by symbol instead of all active instruments.",
        )
        parser.add_argument(
            "--start",
            help="Start date YYYY-MM-DD (inclusive). Omit for full available history.",
        )
        parser.add_argument(
            "--end",
            help="End date YYYY-MM-DD (inclusive). Omit for up to today.",
        )

    def handle(self, *args, **options):
        start = _parse_date(options.get("start"))
        end = _parse_date(options.get("end"))
        symbol = options.get("symbol")

        if symbol:
            try:
                instrument = Instrument.objects.get(symbol=symbol.upper())
            except Instrument.DoesNotExist as exc:
                raise CommandError(
                    f"No Instrument with symbol={symbol.upper()!r}. Add it via admin/shell first."
                ) from exc
            count = sync_instrument_history(instrument, start=start, end=end)
            self.stdout.write(self.style.SUCCESS(f"{instrument.symbol}: {count} bars written"))
            return

        results = sync_active_instruments(start=start, end=end)
        total = sum(results.values())
        for sym, count in sorted(results.items()):
            self.stdout.write(f"  {sym}: {count} bars")
        self.stdout.write(
            self.style.SUCCESS(f"Synced {len(results)} instrument(s), {total} bar(s) total")
        )


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()
