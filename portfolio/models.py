from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

from marketdata.models import Instrument


class Account(models.Model):
    """A tradeable account - paper or (eventually) live. Every order/trade/
    position is scoped to one Account, so paper and live books never mix."""

    class AccountType(models.TextChoices):
        PAPER = "paper", "Paper"
        LIVE = "live", "Live"

    class Broker(models.TextChoices):
        # Paper is the only implementation for now - PSX has no public
        # self-serve order-routing API. See docs/PLAN.md, Phase 6.
        PAPER = "paper", "Paper (simulated)"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="accounts"
    )
    name = models.CharField(max_length=255)
    account_type = models.CharField(
        max_length=8, choices=AccountType.choices, default=AccountType.PAPER
    )
    broker = models.CharField(max_length=16, choices=Broker.choices, default=Broker.PAPER)
    currency = models.CharField(max_length=8, default="PKR")
    cash_balance = models.DecimalField(
        max_digits=16, decimal_places=2, validators=[MinValueValidator(0)]
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["owner", "name"], name="unique_account_name_per_owner")
        ]
        ordering = ["id"]

    def __str__(self):
        return f"{self.name} ({self.get_account_type_display()})"

    @property
    def equity(self) -> Decimal:
        """Cash + mark-to-market value of all open positions, at each
        position's last-known price (see Position.market_value)."""
        return self.cash_balance + sum(
            (p.market_value for p in self.positions.select_related("instrument")), Decimal("0")
        )


class Position(models.Model):
    """An open holding of one instrument within one account."""

    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="positions")
    instrument = models.ForeignKey(Instrument, on_delete=models.PROTECT, related_name="positions")
    quantity = models.PositiveIntegerField()
    avg_entry_price = models.DecimalField(max_digits=14, decimal_places=4)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["account", "instrument"], name="unique_position_per_account_instrument"
            )
        ]
        ordering = ["id"]

    def __str__(self):
        return f"{self.account}: {self.quantity} {self.instrument.symbol} @ {self.avg_entry_price}"

    @property
    def market_value(self) -> Decimal:
        """Last known close price * quantity. Falls back to avg_entry_price
        if no PriceBar exists yet (e.g. a freshly added instrument)."""
        last_bar = self.instrument.price_bars.order_by("-timestamp").first()
        price = last_bar.close if last_bar else self.avg_entry_price
        return price * self.quantity
