import json
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError

from marketdata.models import Instrument, PriceBar
from marketdata.providers.base import Bar
from strategies.backtesting.engine import run_backtest
from strategies.registry import get_strategy_class, registered_keys


class Command(BaseCommand):
    help = "Backtest a registered strategy against stored PriceBar history for one instrument."

    def add_arguments(self, parser):
        parser.add_argument("symbol", help="Instrument symbol, e.g. ENGRO.")
        parser.add_argument("strategy_key", help=f"One of: {', '.join(registered_keys())}")
        parser.add_argument(
            "--params",
            default="{}",
            help="JSON kwargs for the strategy, e.g. '{\"fast_period\": 10}'",
        )
        parser.add_argument("--start", help="Start date YYYY-MM-DD")
        parser.add_argument("--end", help="End date YYYY-MM-DD")
        parser.add_argument("--cash", type=float, default=100_000.0)

    def handle(self, *args, **options):
        try:
            instrument = Instrument.objects.get(symbol=options["symbol"].upper())
        except Instrument.DoesNotExist as exc:
            raise CommandError(f"No Instrument with symbol={options['symbol'].upper()!r}") from exc

        try:
            strategy_cls = get_strategy_class(options["strategy_key"])
        except KeyError as exc:
            raise CommandError(str(exc)) from exc

        try:
            params = json.loads(options["params"])
        except json.JSONDecodeError as exc:
            raise CommandError(f"--params must be valid JSON: {exc}") from exc

        qs = PriceBar.objects.filter(instrument=instrument, timeframe=PriceBar.Timeframe.DAILY)
        if options.get("start"):
            qs = qs.filter(timestamp__date__gte=_parse_date(options["start"]))
        if options.get("end"):
            qs = qs.filter(timestamp__date__lte=_parse_date(options["end"]))
        qs = qs.order_by("timestamp")

        bars = [
            Bar(
                timestamp=row.timestamp,
                open=float(row.open),
                high=float(row.high),
                low=float(row.low),
                close=float(row.close),
                volume=row.volume,
                is_anomaly=row.is_anomaly,
            )
            for row in qs
        ]
        if not bars:
            raise CommandError(
                f"No PriceBar data found for {instrument.symbol}. Run sync_market_data first."
            )

        strategy = strategy_cls(**params)
        result = run_backtest(strategy, bars, initial_cash=options["cash"])

        self.stdout.write(f"Bars: {len(bars)}  Trades: {result.num_trades}")
        self.stdout.write(f"Initial cash: {result.initial_cash:,.2f}")
        self.stdout.write(f"Final equity: {result.final_equity:,.2f}")
        self.stdout.write(f"Total return: {result.total_return:.2%}")
        self.stdout.write(f"CAGR: {result.cagr:.2%}")
        self.stdout.write(f"Max drawdown: {result.max_drawdown:.2%}")
        win_rate = result.win_rate
        self.stdout.write(
            f"Win rate: {win_rate:.2%}"
            if win_rate is not None
            else "Win rate: n/a (no closed trades)"
        )
        sharpe = result.sharpe
        self.stdout.write(f"Sharpe: {sharpe:.2f}" if sharpe is not None else "Sharpe: n/a")


def _parse_date(value: str):
    return datetime.strptime(value, "%Y-%m-%d").date()
