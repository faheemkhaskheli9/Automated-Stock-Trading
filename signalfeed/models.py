"""Watchlist + delivered weekly signals.

The ``signalfeed`` app turns a trained :class:`modeling.TradingModel` into a
plain-language weekly call ("on Monday, ENGRO looks UP ~2.3% into Friday's
close") and pushes it to the operator's phone / inbox. It is **advisory
only** - it never places an order (PSX has no self-serve order API and live
trading is a separate, gated phase).

- :class:`WatchItem` - one row per (instrument, model) pair the operator
  wants a weekly signal for, plus the quality bar that model must clear
  before a signal is actually delivered.
- :class:`WeeklySignal` - one built signal for a given Friday. Always stored
  (even when suppressed or errored) so there is a complete record; Friday's
  actual close is backfilled later for a running hit-rate.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models

from marketdata.models import Instrument
from modeling.models import ModelPrediction, TradingModel

# Target types this app knows how to turn into a direction + magnitude.
SUPPORTED_TARGETS = ("weekday_anchored", "horizon_close", "horizon_return", "direction")


class WatchItem(models.Model):
    """An instrument + the model whose weekly forecast should be delivered
    for it, plus the accuracy gate that model must pass to be sent live."""

    instrument = models.ForeignKey(Instrument, on_delete=models.CASCADE, related_name="watch_items")
    trading_model = models.ForeignKey(
        TradingModel, on_delete=models.CASCADE, related_name="watch_items"
    )
    is_active = models.BooleanField(default=True)
    min_directional_accuracy = models.FloatField(
        default=0.55,
        help_text="Suppress the signal unless the model's trailing out-of-sample "
        "up/down hit-rate is at least this (0-1).",
    )
    min_skill = models.FloatField(
        default=0.0,
        help_text="Suppress the signal unless skill-vs-naive is at least this. "
        "0 disables the check; >0 also requires skill to be computable.",
    )
    min_expected_move_pct = models.FloatField(
        default=1.0,
        help_text="A predicted move smaller than this (in %) is reported FLAT "
        "and not delivered - it is not worth trading.",
    )
    sizing_capital = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
        blank=True,
        help_text="Notional pool a single delivered call is sized against. "
        "0 disables the position-sizing hint. Advisory only - no order is placed.",
    )
    max_position_pct = models.FloatField(
        default=10.0,
        blank=True,
        help_text="Hard cap on one call's suggested size, as a %% of sizing_capital.",
    )
    kelly_fraction = models.FloatField(
        default=0.5,
        blank=True,
        help_text="Fraction of the model's directional edge to bet "
        "(0.5 = half-Kelly). 0 sizes flat at max_position_pct for every "
        "deliverable call.",
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["instrument__symbol"]
        constraints = [
            models.UniqueConstraint(
                fields=["instrument", "trading_model"], name="unique_watchitem_per_model"
            )
        ]

    def __str__(self):
        return f"{self.instrument.symbol} <- {self.trading_model.name}"

    def clean(self):
        errors = {}
        # Sizing config is optional in forms - fall back to the field defaults
        # so a blank submission means "use the defaults", not "invalid".
        if self.sizing_capital is None:
            self.sizing_capital = 0
        if self.max_position_pct is None:
            self.max_position_pct = 10.0
        if self.kelly_fraction is None:
            self.kelly_fraction = 0.5

        spec = self.trading_model.target_spec if self.trading_model_id else None
        ttype = spec.get("type") if isinstance(spec, dict) else None
        if ttype not in SUPPORTED_TARGETS:
            errors["trading_model"] = (
                f"signalfeed can only deliver these target types: {SUPPORTED_TARGETS}; "
                f"this model's target is {ttype!r}."
            )
        if not 0.0 <= self.min_directional_accuracy <= 1.0:
            errors["min_directional_accuracy"] = "Must be between 0 and 1."
        if self.min_expected_move_pct < 0:
            errors["min_expected_move_pct"] = "Must be >= 0."
        if self.sizing_capital is not None and self.sizing_capital < 0:
            errors["sizing_capital"] = "Must be >= 0."
        if not 0.0 < self.max_position_pct <= 100.0:
            errors["max_position_pct"] = "Must be between 0 (exclusive) and 100."
        if not 0.0 <= self.kelly_fraction <= 1.0:
            errors["kelly_fraction"] = "Must be between 0 and 1."
        if errors:
            raise ValidationError(errors)


class WeeklySignal(models.Model):
    """One weekly call for a single Friday, kept regardless of outcome."""

    class Direction(models.TextChoices):
        UP = "up", "Up"
        DOWN = "down", "Down"
        FLAT = "flat", "Flat"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending delivery"
        SENT = "sent", "Sent"
        SUPPRESSED = "suppressed", "Suppressed (failed gate)"
        ERROR = "error", "Error"

    watch_item = models.ForeignKey(
        WatchItem, on_delete=models.SET_NULL, null=True, blank=True, related_name="signals"
    )
    instrument = models.ForeignKey(
        Instrument, on_delete=models.CASCADE, related_name="weekly_signals"
    )
    trading_model = models.ForeignKey(
        TradingModel,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="weekly_signals",
    )
    model_prediction = models.ForeignKey(
        ModelPrediction, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    as_of = models.DateField(help_text="The Monday the call was made for.")
    target_date = models.DateField(help_text="The Friday the call is about.")

    direction = models.CharField(max_length=8, choices=Direction.choices)
    expected_return_pct = models.FloatField(
        null=True, blank=True, help_text="Signed predicted move into the target close, in %."
    )
    predicted_close = models.FloatField(null=True, blank=True)
    reference_close = models.FloatField(
        null=True, blank=True, help_text="Last close known when the call was made."
    )
    flat_threshold_pct = models.FloatField(default=1.0)
    confidence = models.FloatField(
        null=True, blank=True, help_text="Model's trailing directional accuracy at send time."
    )
    model_stats = models.JSONField(default=dict, blank=True)

    # Advisory position-sizing hint (only populated for a deliverable UP/DOWN
    # call whose watch item has sizing_capital > 0). No order is ever placed.
    suggested_fraction = models.FloatField(
        null=True, blank=True, help_text="Suggested fraction of sizing_capital for this call."
    )
    suggested_notional = models.FloatField(null=True, blank=True)
    suggested_shares = models.IntegerField(null=True, blank=True)
    sizing_basis = models.JSONField(
        default=dict, blank=True, help_text="Snapshot of the sizing inputs, for audit."
    )

    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    suppression_reason = models.CharField(max_length=255, blank=True)
    channels = models.JSONField(default=list, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    actual_close = models.FloatField(null=True, blank=True)
    actual_return_pct = models.FloatField(null=True, blank=True)
    was_correct = models.BooleanField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-target_date", "instrument__symbol"]
        constraints = [
            models.UniqueConstraint(
                fields=["instrument", "trading_model", "target_date"],
                name="unique_weekly_signal_per_model_target",
            )
        ]

    def __str__(self):
        return f"{self.instrument.symbol} {self.direction} -> {self.target_date}"
