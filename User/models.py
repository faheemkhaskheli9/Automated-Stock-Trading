from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


class UserProfile(models.Model):
    """Trading-related profile data for a Django auth user.

    Broker credentials are intentionally not stored here yet - they'll be
    added once the `BrokerAdapter` interface (Phase 3) defines what a
    credential actually needs to look like per broker, and will be
    encrypted at rest rather than stored as plain fields.
    """

    class RiskTolerance(models.TextChoices):
        CONSERVATIVE = "conservative", "Conservative"
        MODERATE = "moderate", "Moderate"
        AGGRESSIVE = "aggressive", "Aggressive"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="trading_profile",
    )
    risk_tolerance = models.CharField(
        max_length=20,
        choices=RiskTolerance.choices,
        default=RiskTolerance.MODERATE,
    )
    max_daily_loss_pct = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=2.0,
        validators=[MinValueValidator(0)],
        help_text="Max percent of account equity this user's strategies may lose in a day before trading halts.",
    )
    max_position_size_pct = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=10.0,
        validators=[MinValueValidator(0)],
        help_text="Max percent of account equity in a single position.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Trading profile for {self.user}"
