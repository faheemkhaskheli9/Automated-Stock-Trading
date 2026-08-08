from django.db import models

from marketdata.models import Instrument
from portfolio.models import Account
from strategies.models import Strategy
from strategies.signals import Action


class DailyEquitySnapshot(models.Model):
    """Account equity captured once per calendar day, the first time it's
    needed - the baseline `check_max_daily_loss` measures against. Without
    this, "daily loss" has no fixed starting point to compare current
    equity to."""

    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="equity_snapshots")
    date = models.DateField()
    opening_equity = models.DecimalField(max_digits=16, decimal_places=2)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["account", "date"], name="unique_snapshot_per_account_day"
            )
        ]

    def __str__(self):
        return f"{self.account} @ {self.date}: {self.opening_equity}"


class RiskDecision(models.Model):
    """Audit trail: every risk evaluation, approved or not, with why -
    per docs/PLAN.md's "every rejected/approved decision is logged"."""

    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="risk_decisions")
    instrument = models.ForeignKey(
        Instrument, on_delete=models.PROTECT, related_name="risk_decisions"
    )
    strategy = models.ForeignKey(Strategy, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(
        max_length=8, choices=[(a.value, a.name) for a in Action if a != Action.HOLD]
    )
    quantity = models.PositiveIntegerField()
    approved = models.BooleanField()
    reason = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        verdict = "approved" if self.approved else "rejected"
        return f"{verdict}: {self.action} {self.quantity} {self.instrument.symbol} ({self.reason or 'ok'})"
