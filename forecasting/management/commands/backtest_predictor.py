"""Walk-forward backtest of a single `forecasting` predictor, printed as a table.

    python manage.py backtest_predictor OGDC ridge --start 2023-01-01 --end 2025-01-01

Prints a per-fold table, the pooled regression / directional / skill numbers,
the naive-baseline comparison and a "long if up" trading translation. Warns
loudly if the result looks leaky (implausible out-of-sample skill).
"""

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand, CommandError

from forecasting.backtesting.engine import looks_leaky, walk_forward
from forecasting.backtesting.walkforward import EXPANDING, ROLLING
from forecasting.features import DEFAULT_PROVIDERS
from forecasting.registry import registered_keys


class Command(BaseCommand):
    help = "Leakage-safe walk-forward backtest of one registered forecasting predictor."

    def add_arguments(self, parser):
        parser.add_argument("symbol")
        parser.add_argument("predictor_key")
        parser.add_argument("--start", required=True, help="ISO date, inclusive of feature rows")
        parser.add_argument("--end", required=True, help="ISO date, latest usable label")
        parser.add_argument("--exchange", default="PSX")
        parser.add_argument("--timezone", default="Asia/Karachi")
        parser.add_argument("--scheme", choices=[EXPANDING, ROLLING], default=EXPANDING)
        parser.add_argument("--train-span", type=int, default=250)
        parser.add_argument("--test-span", type=int, default=21)
        parser.add_argument("--step", type=int, default=21)
        parser.add_argument("--gap", type=int, default=1)
        parser.add_argument(
            "--providers",
            default=",".join(DEFAULT_PROVIDERS),
            help="comma-separated research providers, or 'none' for price-only",
        )
        parser.add_argument("--params", default="{}", help="JSON dict of predictor params")
        parser.add_argument("--allow-short", action="store_true")
        parser.add_argument("--long-threshold", type=float, default=0.0)
        parser.add_argument("--cost-bps", type=float, default=0.0)
        parser.add_argument("--cash", type=float, default=100_000.0)

    def handle(self, *args, **opts):
        if opts["predictor_key"] not in registered_keys():
            raise CommandError(
                f"Unknown predictor {opts['predictor_key']!r}. Registered: {registered_keys()}"
            )
        try:
            params = json.loads(opts["params"])
            if not isinstance(params, dict):
                raise ValueError
        except ValueError as exc:
            raise CommandError("--params must be a JSON object") from exc

        zone = ZoneInfo(opts["timezone"])
        start = datetime.fromisoformat(opts["start"]).replace(tzinfo=zone)
        end = datetime.fromisoformat(opts["end"]).replace(tzinfo=zone)
        providers = (
            []
            if opts["providers"].strip().lower() == "none"
            else [p.strip() for p in opts["providers"].split(",") if p.strip()]
        )

        try:
            result = walk_forward(
                opts["predictor_key"],
                opts["symbol"],
                start,
                end,
                params=params,
                scheme=opts["scheme"],
                train_span=opts["train_span"],
                test_span=opts["test_span"],
                step=opts["step"],
                gap=opts["gap"],
                provider_keys=providers,
                exchange=opts["exchange"],
                exchange_timezone=opts["timezone"],
                allow_short=opts["allow_short"],
                long_threshold=opts["long_threshold"],
                cost_bps=opts["cost_bps"],
                initial_cash=opts["cash"],
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(result.fold_table())
        self.stdout.write("")
        self.stdout.write(
            f"folds run:      {len(result.folds)}  (skipped {len(result.skipped_folds)})"
        )
        self.stdout.write(f"OOS rows:       {result.metrics.get('n')}")
        self.stdout.write(
            f"MAE / RMSE:     {result.metrics.get('mae'):.4f} / {result.metrics.get('rmse'):.4f}"
        )
        self.stdout.write(
            f"MAPE / R2:      {result.metrics.get('mape')} / {result.metrics.get('r2')}"
        )
        self.stdout.write(f"directional:    {result.metrics.get('directional_accuracy')}")
        self.stdout.write(f"naive MAE:      {result.metrics.get('naive_mae'):.4f}")
        self.stdout.write(
            self.style.SUCCESS(f"skill vs naive: {result.skill_vs_naive}")
            if (result.skill_vs_naive or 0) > 0
            else f"skill vs naive: {result.skill_vs_naive}"
        )
        t = result.trading
        self.stdout.write("")
        self.stdout.write(
            f"trading (long-if-up): total_return={t.get('total_return')}  "
            f"max_dd={t.get('max_drawdown')}  sharpe={t.get('sharpe')}  "
            f"hit_rate={t.get('hit_rate')}  trades={t.get('num_trades')}"
        )
        if looks_leaky(result):
            self.stdout.write(
                self.style.ERROR(
                    "WARNING: out-of-sample skill is implausibly high - this predictor "
                    "may be peeking at the future. Investigate before trusting it."
                )
            )
