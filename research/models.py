"""Storage for raw external signals and for frozen point-in-time feature
bundles.

The raw tables (`NewsItem`, `CompanyFundamental`, `SocialMention`) all carry
an explicit "when did this become public" timestamp so providers can filter
to ``<= as_of``. `ResearchSnapshot` caches an assembled `FeatureBundle` so a
backtest and the live daily-prediction job read byte-identical inputs.
"""

from django.db import models


class NewsItem(models.Model):
    """One news headline about an instrument. `published_at` is the
    point-in-time key - a provider building features as of date D only sees
    rows with `published_at <= D`."""

    symbol = models.CharField(max_length=32)
    exchange = models.CharField(max_length=16, default="PSX")
    headline = models.CharField(max_length=512)
    url = models.URLField(max_length=1024)
    url_hash = models.CharField(
        max_length=64,
        unique=True,
        help_text="sha256 of the canonical URL - the idempotency key for re-ingestion.",
    )
    source = models.CharField(max_length=128, blank=True)
    published_at = models.DateTimeField()
    sentiment = models.FloatField(
        null=True, blank=True, help_text="VADER compound score in [-1, 1]; null if not scored."
    )
    ingested_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-published_at"]
        indexes = [models.Index(fields=["exchange", "symbol", "-published_at"])]

    def __str__(self):
        return f"{self.symbol}: {self.headline[:60]}"


class CompanyFundamental(models.Model):
    """A point-in-time fundamentals snapshot. STUB: only a manual/CSV loader
    exists today - live scraping of PSX filings is deferred (needs a data
    source). `as_of_report_date` is when the figures became public."""

    symbol = models.CharField(max_length=32)
    exchange = models.CharField(max_length=16, default="PSX")
    as_of_report_date = models.DateField()
    ratios = models.JSONField(
        default=dict, help_text='e.g. {"pe": 8.1, "pb": 1.2, "eps": 4.3, "de": 0.6}'
    )
    source = models.CharField(max_length=128, blank=True)
    ingested_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["symbol", "-as_of_report_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["exchange", "symbol", "as_of_report_date"],
                name="unique_fundamental_per_symbol_report_date",
            )
        ]

    def __str__(self):
        return f"{self.symbol} fundamentals @ {self.as_of_report_date}"


class SocialMention(models.Model):
    """A social-media mention of an instrument. STUB: interface + fixture
    loader only - live X/Reddit/StockTwits ingestion needs credentials and
    is deferred. `posted_at` is the point-in-time key."""

    symbol = models.CharField(max_length=32)
    exchange = models.CharField(max_length=16, default="PSX")
    platform = models.CharField(max_length=32)
    external_id = models.CharField(max_length=128, blank=True)
    posted_at = models.DateTimeField()
    sentiment = models.FloatField(null=True, blank=True)
    reach = models.IntegerField(
        default=0, help_text="followers / upvotes / views - platform-dependent"
    )
    ingested_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-posted_at"]
        indexes = [models.Index(fields=["exchange", "symbol", "-posted_at"])]

    def __str__(self):
        return f"{self.symbol} @ {self.platform} ({self.posted_at:%Y-%m-%d})"


class ResearchSnapshot(models.Model):
    """A frozen, assembled `FeatureBundle` for (symbol, exchange, as_of).

    Written by `research.services.get_or_build_snapshot`. Backtests and the
    daily prediction job read this instead of recomputing, so results are
    reproducible and the point-in-time inputs are auditable after the fact.
    """

    symbol = models.CharField(max_length=32)
    exchange = models.CharField(max_length=16, default="PSX")
    as_of = models.DateTimeField()
    features = models.JSONField(default=dict)
    sources = models.JSONField(default=list)
    provider_keys = models.JSONField(
        default=list, help_text="Which feature providers contributed to this snapshot."
    )
    built_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["symbol", "-as_of"]
        constraints = [
            models.UniqueConstraint(
                fields=["exchange", "symbol", "as_of"],
                name="unique_snapshot_per_symbol_as_of",
            )
        ]
        indexes = [models.Index(fields=["exchange", "symbol", "-as_of"])]

    def __str__(self):
        return f"{self.symbol} snapshot @ {self.as_of:%Y-%m-%d} ({len(self.features)} features)"
