"""Walk-forward backtesting of a configured ``modeling.TradingModel``.

A :class:`Backtest` is a config row (which model, which fold scheme, how
forecasts become positions, what trading costs apply). Running it produces a
:class:`BacktestRun` with per-fold accuracy (:class:`BacktestFold`), the
pooled predicted-vs-actual series (:class:`BacktestPrediction`) and the
simulated trades (:class:`BacktestTrade`).

``modeling`` already trains a model against a single trailing holdout; this
app is the repeated-retrain-through-time view that the holdout can't give,
plus a forecast -> trade -> equity-curve translation. Leakage safety is
inherited from ``modeling.dataset`` (every feature is point-in-time and a
training row survives only once its label was observable) and tightened
per fold in ``backtesting.engine``.
"""

from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from marketdata.models import Instrument
from modeling.models import TradingModel

# Forecast targets this v1 can turn into a position. Multi-output
# (``multistep``) and calendar-anchored (``weekday_anchored``) targets are
# out of scope - a single scalar per decision is what the sizing logic needs.
SUPPORTED_TARGETS = ("horizon_close", "horizon_return", "direction")


class Backtest(models.Model):
    class Scheme(models.TextChoices):
        EXPANDING = "expanding", "Expanding window"
        ROLLING = "rolling", "Rolling window"

    name = models.CharField(max_length=255)
    model = models.ForeignKey(TradingModel, on_delete=models.CASCADE, related_name="backtests")
    scheme = models.CharField(max_length=12, choices=Scheme.choices, default=Scheme.EXPANDING)
    train_span = models.PositiveIntegerField(
        default=250, help_text="Sessions of training history per fold (rolling: window size)."
    )
    test_span = models.PositiveIntegerField(
        default=21, help_text="Sessions scored per fold before the next retrain."
    )
    step = models.PositiveIntegerField(
        default=21, help_text="Sessions the window advances between folds."
    )
    gap = models.PositiveIntegerField(
        default=1, help_text="Embargo sessions left between a fold's train end and its test start."
    )
    start = models.DateField(null=True, blank=True)
    end = models.DateField(null=True, blank=True)

    long_threshold = models.FloatField(
        default=0.0,
        help_text=(
            "Go long only above this. horizon_close: min fractional gap over the "
            "decision close; horizon_return: min predicted return; direction: min P(up) "
            "above 0.5."
        ),
    )
    allow_short = models.BooleanField(
        default=False, help_text="Take symmetric short positions on a bearish forecast."
    )
    initial_cash = models.FloatField(default=100_000.0)
    commission_bps = models.FloatField(default=0.0)
    slippage_bps = models.FloatField(default=0.0)
    is_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.model.name})"

    def clean(self):
        errors = {}
        for field in ("train_span", "test_span", "step"):
            if getattr(self, field) < 1:
                errors[field] = "Must be at least 1 session."
        if self.initial_cash <= 0:
            errors["initial_cash"] = "Must be positive."
        for field in ("commission_bps", "slippage_bps"):
            if not 0 <= getattr(self, field) < 10_000:
                errors[field] = "Must be between 0 and 9,999 basis points."
        if self.start and self.end and self.start >= self.end:
            errors["end"] = "End date must be after the start date."

        if self.model_id:
            ttype = (self.model.target_spec or {}).get("type")
            if ttype not in SUPPORTED_TARGETS:
                errors["model"] = (
                    f"This model's target is {ttype!r}; backtesting supports "
                    f"{SUPPORTED_TARGETS}."
                )
        if errors:
            raise ValidationError(errors)

    @property
    def target_type(self) -> str:
        return (self.model.target_spec or {}).get("type", "")


class BacktestRun(models.Model):
    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"

    backtest = models.ForeignKey(Backtest, on_delete=models.CASCADE, related_name="runs")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.RUNNING)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    n_folds = models.PositiveIntegerField(null=True, blank=True)
    n_predictions = models.PositiveIntegerField(null=True, blank=True)
    n_trades = models.PositiveIntegerField(null=True, blank=True)
    metrics = models.JSONField(default=dict, blank=True)
    equity_curve = models.JSONField(
        default=list, blank=True, help_text="[[iso_date, equity], ...] for the pooled portfolio."
    )
    error = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return f"{self.backtest.name} run #{self.pk} ({self.status})"


class BacktestFold(models.Model):
    run = models.ForeignKey(BacktestRun, on_delete=models.CASCADE, related_name="folds")
    fold_index = models.PositiveIntegerField()
    train_start = models.DateField()
    train_end = models.DateField()
    test_start = models.DateField()
    test_end = models.DateField()
    n_train = models.PositiveIntegerField(default=0)
    n_test = models.PositiveIntegerField(default=0)
    metrics = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["run", "fold_index"]
        constraints = [
            models.UniqueConstraint(fields=["run", "fold_index"], name="unique_fold_per_run")
        ]

    def __str__(self):
        return f"{self.run} fold {self.fold_index}"


class BacktestPrediction(models.Model):
    run = models.ForeignKey(BacktestRun, on_delete=models.CASCADE, related_name="predictions")
    instrument = models.ForeignKey(
        Instrument, on_delete=models.CASCADE, related_name="backtest_predictions"
    )
    fold_index = models.PositiveIntegerField()
    as_of = models.DateTimeField()
    target_date = models.DateField()
    predicted_value = models.FloatField(null=True, blank=True)
    actual_value = models.FloatField(null=True, blank=True)
    abs_error = models.FloatField(null=True, blank=True)
    position = models.SmallIntegerField(default=0, help_text="-1 short, 0 flat, 1 long.")

    class Meta:
        ordering = ["target_date", "instrument_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["run", "instrument", "target_date"],
                name="unique_backtest_prediction",
            )
        ]

    def __str__(self):
        return f"{self.run} {self.instrument.symbol} -> {self.target_date}"


class BacktestTrade(models.Model):
    run = models.ForeignKey(BacktestRun, on_delete=models.CASCADE, related_name="trades")
    instrument = models.ForeignKey(
        Instrument, on_delete=models.CASCADE, related_name="backtest_trades"
    )
    direction = models.SmallIntegerField(default=1, help_text="1 long, -1 short.")
    entry_date = models.DateField()
    exit_date = models.DateField()
    entry_price = models.FloatField()
    exit_price = models.FloatField()
    shares = models.FloatField()
    fees = models.FloatField(default=0.0)
    pnl = models.FloatField(default=0.0)
    return_pct = models.FloatField(default=0.0)

    class Meta:
        ordering = ["run", "entry_date"]

    def __str__(self):
        return f"{self.run} {self.instrument.symbol} {self.entry_date}..{self.exit_date}"
