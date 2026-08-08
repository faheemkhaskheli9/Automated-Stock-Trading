from django.db import models

from marketdata.models import Instrument
from portfolio.models import Account
from strategies.models import Strategy


class Order(models.Model):
    """One order, submitted through a BrokerAdapter (see brokers/base.py).

    Status models the full lifecycle described in docs/PLAN.md even though
    PaperBroker (the only adapter for now) resolves PENDING -> SUBMITTED ->
    FILLED/REJECTED synchronously in one call - a real broker adapter later
    may leave orders SUBMITTED for a while before a fill/rejection arrives.
    """

    class Side(models.TextChoices):
        BUY = "buy", "Buy"
        SELL = "sell", "Sell"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SUBMITTED = "submitted", "Submitted"
        FILLED = "filled", "Filled"
        REJECTED = "rejected", "Rejected"
        CANCELLED = "cancelled", "Cancelled"

    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="orders")
    instrument = models.ForeignKey(Instrument, on_delete=models.PROTECT, related_name="orders")
    strategy = models.ForeignKey(
        Strategy,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders",
        help_text="The Strategy whose signal produced this order, if any (blank for manual/API orders).",
    )
    side = models.CharField(max_length=4, choices=Side.choices)
    quantity = models.PositiveIntegerField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    filled_quantity = models.PositiveIntegerField(default=0)
    filled_price = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    rejection_reason = models.CharField(max_length=255, blank=True)
    broker_order_id = models.CharField(
        max_length=64,
        blank=True,
        help_text="ID assigned by the broker adapter. Blank/local-only for PaperBroker.",
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    filled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["account", "status"])]

    def __str__(self):
        return f"{self.side} {self.quantity} {self.instrument.symbol} ({self.status})"


class Trade(models.Model):
    """A fill against an Order. Modeled separately from Order (rather than
    just fields on Order) so a future broker adapter that fills orders in
    multiple partial executions doesn't require a schema change."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="trades")
    quantity = models.PositiveIntegerField()
    price = models.DecimalField(max_digits=14, decimal_places=4)
    executed_at = models.DateTimeField()

    class Meta:
        ordering = ["executed_at"]

    def __str__(self):
        return f"{self.quantity} @ {self.price} for order #{self.order_id}"
