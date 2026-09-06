"""Persistence for the strict-path walk-forward backtester.

``forecasting/backtesting/`` (the library) evaluates a single registered
``forecasting.BasePredictor`` over point-in-time folds and returns a
:class:`~forecasting.backtesting.engine.WalkForwardResult`. That result is
throw-away - the ``backtest_predictor`` command just prints it.

:class:`ForecastBacktestRun` freezes one such evaluation: the config that was
run (predictor key + params + symbol + fold scheme + trading rule) and the
results (per-fold table, pooled predicted-vs-actual series, regression /
directional / skill metrics, the long-if-up trading translation and its
equity curve). It is deliberately **one flat row** - there is no
admin-configured "predictor model" object on this path (that intent lives in
``modeling.TradingModel``), so a run carries its own config.

Mirrors ``backtesting.models.BacktestRun`` in spirit; the writer
(``forecasting.services.run_forecast_backtest``) never raises - a failure is
recorded on the row with ``status="failed"``.
"""

from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

# Basis-point ceiling shared with ``backtesting.models`` - a sanity bound, not
# a real-world limit.
_BPS_CEILING = 10_000


class ForecastBacktestRun(models.Model):
    class Scheme(models.TextChoices):
        EXPANDING = "expanding", "Expanding window"
        ROLLING = "rolling", "Rolling window"

    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"

    # --- config -------------------------------------------------------------
    name = models.CharField(max_length=255, blank=True)
    predictor_key = models.CharField(
        max_length=64, help_text="A key registered in forecasting.registry (e.g. 'ridge')."
    )
    params = models.JSONField(default=dict, blank=True, help_text="Predictor constructor kwargs.")
    symbol = models.CharField(max_length=32)
    exchange = models.CharField(max_length=16, default="PSX")
    exchange_timezone = models.CharField(max_length=64, default="Asia/Karachi")
    provider_keys = models.JSONField(
        default=list,
        blank=True,
        help_text="research feature providers to assemble; [] means price-only.",
    )
    scheme = models.CharField(max_length=12, choices=Scheme.choices, default=Scheme.EXPANDING)
    train_span = models.PositiveIntegerField(
        default=250, help_text="Decision rows of training history per fold (rolling: window size)."
    )
    test_span = models.PositiveIntegerField(
        default=21, help_text="Rows scored per fold before the next retrain."
    )
    step = models.PositiveIntegerField(
        default=21, help_text="Rows the window advances between folds."
    )
    gap = models.PositiveIntegerField(
        default=1, help_text="Embargo rows between a fold's train end and its test start."
    )
    start = models.DateField(help_text="Earliest feature row assembled.")
    end = models.DateField(help_text="Latest usable label.")
    allow_short = models.BooleanField(default=False)
    long_threshold = models.FloatField(default=0.0)
    cost_bps = models.FloatField(
        default=0.0, help_text="Round-trip cost charged on position change."
    )
    initial_cash = models.FloatField(default=100_000.0)

    # --- results ----------------------------------------------------------
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.RUNNING)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    n_folds = models.PositiveIntegerField(null=True, blank=True)
    n_skipped_folds = models.PositiveIntegerField(null=True, blank=True)
    n_predictions = models.PositiveIntegerField(null=True, blank=True)
    metrics = models.JSONField(default=dict, blank=True, help_text="Pooled OOS regression scores.")
    naive_metrics = models.JSONField(default=dict, blank=True)
    trading = models.JSONField(default=dict, blank=True, help_text="Long-if-up translation stats.")
    equity_curve = models.JSONField(
        default=list,
        blank=True,
        help_text="[[iso_date, equity], ...] from the trading translation.",
    )
    folds = models.JSONField(
        default=list, blank=True, help_text="Per-fold windows + metrics, oldest first."
    )
    predictions = models.JSONField(
        default=list, blank=True, help_text="Pooled [{fold, as_of, target_date, anchor, ...}]."
    )
    skipped_folds = models.JSONField(default=list, blank=True)
    looks_leaky = models.BooleanField(
        default=False, help_text="engine.looks_leaky verdict - implausible OOS skill."
    )
    error = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        label = self.name or f"{self.predictor_key} {self.symbol}"
        return f"{label} run #{self.pk} ({self.status})"

    @property
    def skill_vs_naive(self):
        return (self.metrics or {}).get("skill_vs_naive")

    def clean(self):
        errors = {}
        # Validate the predictor key against the live registry. Import here so
        # importing this module (e.g. at migration time) stays Django-only.
        try:
            from .registry import registered_keys

            keys = registered_keys()
            if self.predictor_key and self.predictor_key not in keys:
                errors["predictor_key"] = (
                    f"Unknown predictor {self.predictor_key!r}. Registered: {keys}"
                )
        except Exception:  # noqa: BLE001 - registry not ready is not a validation error
            pass

        if not isinstance(self.params, dict):
            errors["params"] = "Must be a JSON object."
        if not isinstance(self.provider_keys, list):
            errors["provider_keys"] = "Must be a JSON list of provider keys."

        for field in ("train_span", "test_span", "step"):
            if getattr(self, field) < 1:
                errors[field] = "Must be at least 1 row."
        if self.initial_cash <= 0:
            errors["initial_cash"] = "Must be positive."
        if not 0 <= self.cost_bps < _BPS_CEILING:
            errors["cost_bps"] = f"Must be between 0 and {_BPS_CEILING - 1} basis points."
        if self.start and self.end and self.start >= self.end:
            errors["end"] = "End date must be after the start date."

        if errors:
            raise ValidationError(errors)
