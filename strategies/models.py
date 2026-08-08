from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from marketdata.models import Instrument

from .signals import Action


class Strategy(models.Model):
    """A configured instance of a registered strategy class - what actually
    runs, as managed data rather than a hardcoded code path.

    `key` isn't a model-level `choices=` field: the strategy registry is
    only guaranteed populated once `strategies.apps.StrategiesConfig.ready()`
    has run (it imports rules/manual/ml so their @register_strategy
    decorators fire), which happens after this module is first imported.
    Validity is checked in `clean()` instead - see `registry.get_strategy_class`.
    """

    name = models.CharField(max_length=255)
    key = models.CharField(
        max_length=64,
        help_text="Registered strategy key, e.g. 'ma_crossover'. See strategies.registry.",
    )
    params = models.JSONField(
        default=dict,
        blank=True,
        help_text="Keyword args passed to the strategy class, e.g. {'fast_period': 10}.",
    )
    instruments = models.ManyToManyField(Instrument, related_name="strategies", blank=True)
    is_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "strategies"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.key})"

    def clean(self):
        from .registry import get_strategy_class

        try:
            get_strategy_class(self.key)
        except KeyError as exc:
            raise ValidationError({"key": str(exc)}) from exc

    def build(self):
        """Instantiate the configured strategy class with `params`."""
        from .registry import get_strategy_class

        return get_strategy_class(self.key)(**self.params)


class ManualSignal(models.Model):
    """An operator-entered trading decision for one instrument/date, fed
    through the same Signal pipeline as computed strategies via
    ManualSignalStrategy."""

    instrument = models.ForeignKey(
        Instrument, on_delete=models.CASCADE, related_name="manual_signals"
    )
    date = models.DateField()
    action = models.CharField(max_length=8, choices=[(a.value, a.name) for a in Action])
    note = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["instrument", "date"], name="unique_manual_signal_per_day"
            )
        ]
        ordering = ["-date"]

    def __str__(self):
        return f"{self.instrument.symbol} {self.date} -> {self.action}"
