from django.db import models


class Instrument(models.Model):
    """A tradeable symbol on an exchange. PSX only for now, but `exchange`
    keeps the door open for other markets without a schema change."""

    symbol = models.CharField(max_length=32)
    name = models.CharField(max_length=255, blank=True)
    exchange = models.CharField(max_length=16, default="PSX")
    sector = models.CharField(max_length=128, blank=True)
    is_active = models.BooleanField(
        default=True,
        help_text="Whether this instrument should be included in data backfills and strategies.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["exchange", "symbol"], name="unique_symbol_per_exchange"
            )
        ]
        ordering = ["symbol"]

    def __str__(self):
        return f"{self.symbol} ({self.exchange})"


class PriceBar(models.Model):
    """A single OHLCV bar for an instrument.

    PSX's public data (via `psxdata`) is end-of-day only, so `timeframe`
    defaults to daily - but the field exists now so intraday bars from a
    future data source aren't a schema migration away.
    """

    class Timeframe(models.TextChoices):
        DAILY = "1d", "Daily"

    instrument = models.ForeignKey(Instrument, on_delete=models.CASCADE, related_name="price_bars")
    timeframe = models.CharField(max_length=8, choices=Timeframe.choices, default=Timeframe.DAILY)
    timestamp = models.DateTimeField(help_text="Bar date/time, in UTC.")
    open = models.DecimalField(max_digits=14, decimal_places=4)
    high = models.DecimalField(max_digits=14, decimal_places=4)
    low = models.DecimalField(max_digits=14, decimal_places=4)
    close = models.DecimalField(max_digits=14, decimal_places=4)
    volume = models.BigIntegerField(default=0)
    is_anomaly = models.BooleanField(
        default=False,
        help_text="Flagged by the data provider as a likely data-quality issue.",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["instrument", "timeframe", "timestamp"],
                name="unique_bar_per_instrument_timeframe_timestamp",
            )
        ]
        ordering = ["instrument", "timestamp"]
        indexes = [
            models.Index(fields=["instrument", "timeframe", "-timestamp"]),
        ]

    def __str__(self):
        return f"{self.instrument.symbol} {self.timeframe} @ {self.timestamp:%Y-%m-%d}"
