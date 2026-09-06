from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from marketdata.models import Instrument


class TradingModel(models.Model):
    """A user-configured ML model: an estimator + an input (feature) spec +
    an output (target) spec, trainable and reusable for prediction.

    ``estimator_key`` is not a ``choices=`` field for the same reason
    ``strategies.Strategy.key`` isn't - the estimator registry is only
    populated once ``modeling.apps.ModelingConfig.ready()`` has imported the
    concrete estimator modules. Validity is enforced in ``clean()``.
    """

    name = models.CharField(max_length=255)
    estimator_key = models.CharField(
        max_length=64,
        help_text="Registered estimator key, e.g. 'ridge'. See /modeling/estimators/.",
    )
    estimator_params = models.JSONField(
        default=dict, blank=True, help_text="Keyword args for the estimator, e.g. {'alpha': 0.5}."
    )
    feature_spec = models.JSONField(
        default=list,
        blank=True,
        help_text="List of input-feature source descriptors. See modeling.features.",
    )
    target_spec = models.JSONField(
        default=dict,
        blank=True,
        help_text="Output/target descriptor, e.g. {'type': 'horizon_close', 'horizon': 1}.",
    )
    instruments = models.ManyToManyField(
        Instrument,
        related_name="trading_models",
        blank=True,
        help_text="Symbols whose history is pooled for training / available for prediction.",
    )
    train_start = models.DateField(null=True, blank=True)
    train_end = models.DateField(null=True, blank=True)
    holdout_fraction = models.FloatField(
        default=0.2, help_text="Trailing fraction of rows held out for evaluation (0.05-0.5)."
    )
    is_active = models.BooleanField(default=False)
    artifact_path = models.CharField(max_length=500, blank=True)
    metrics = models.JSONField(default=dict, blank=True)
    trained_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.estimator_key})"

    def clean(self):
        from . import features, targets
        from .registry import get_estimator

        errors = {}
        try:
            spec = get_estimator(self.estimator_key)
            if not spec.available:
                errors["estimator_key"] = f"Estimator {self.estimator_key!r} is not available here."
        except KeyError as exc:
            errors["estimator_key"] = str(exc)

        try:
            features.validate_spec(self.feature_spec)
        except ValueError as exc:
            errors["feature_spec"] = str(exc)
        try:
            targets.validate_spec(self.target_spec)
        except ValueError as exc:
            errors["target_spec"] = str(exc)

        if "estimator_key" not in errors and "target_spec" not in errors:
            est_task = get_estimator(self.estimator_key).task
            tgt_task = targets.task_of(self.target_spec)
            if est_task != tgt_task:
                errors["estimator_key"] = (
                    f"Estimator is for {est_task}, but the target is a {tgt_task} problem."
                )

        if not 0.05 <= self.holdout_fraction <= 0.5:
            errors["holdout_fraction"] = "Must be between 0.05 and 0.5."

        if errors:
            raise ValidationError(errors)

    @property
    def task(self) -> str:
        from . import targets

        return targets.task_of(self.target_spec)


class ModelTrainingRun(models.Model):
    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"

    model = models.ForeignKey(TradingModel, on_delete=models.CASCADE, related_name="runs")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.RUNNING)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    rows = models.PositiveIntegerField(null=True, blank=True)
    feature_count = models.PositiveIntegerField(null=True, blank=True)
    metrics = models.JSONField(default=dict, blank=True)
    artifact_path = models.CharField(max_length=500, blank=True)
    error = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return f"{self.model.name} run #{self.pk} ({self.status})"


class ModelPrediction(models.Model):
    """One stored forecast. ``actual_value`` / ``abs_error`` are filled by
    ``prediction.backfill_actuals`` once the target session's bar exists."""

    model = models.ForeignKey(TradingModel, on_delete=models.CASCADE, related_name="predictions")
    instrument = models.ForeignKey(
        Instrument, on_delete=models.CASCADE, related_name="model_predictions"
    )
    as_of = models.DateTimeField(help_text="Decision timestamp the features were built at.")
    target_date = models.DateField()
    predicted_value = models.FloatField(null=True, blank=True)
    predicted_json = models.JSONField(
        null=True, blank=True, help_text="Vector prediction (multistep) or class probabilities."
    )
    actual_value = models.FloatField(null=True, blank=True)
    abs_error = models.FloatField(null=True, blank=True)
    feature_hash = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-target_date", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["model", "instrument", "target_date"],
                name="unique_prediction_per_model_instrument_date",
            )
        ]

    def __str__(self):
        return f"{self.model.name} {self.instrument.symbol} -> {self.target_date}"
