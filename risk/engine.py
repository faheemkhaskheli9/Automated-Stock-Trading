"""Runs every pre-trade check for one candidate order and records the
verdict. This is the only entry point execution.services should call -
individual checks (checks.py) are implementation detail.
"""

from dataclasses import dataclass
from decimal import Decimal

from marketdata.models import Instrument
from portfolio.models import Account
from strategies.models import Strategy
from strategies.signals import Action
from User.models import UserProfile

from . import checks
from .models import RiskDecision

# Fallback risk preferences when the account owner has no UserProfile yet -
# mirrors UserProfile's own field defaults (see User/models.py) so behavior
# is identical whether or not a profile row exists.
_DEFAULT_MAX_DAILY_LOSS_PCT = Decimal("2.0")
_DEFAULT_MAX_POSITION_SIZE_PCT = Decimal("10.0")


@dataclass(frozen=True)
class RiskCheckResult:
    approved: bool
    reason: str = ""


def _risk_profile(account: Account) -> tuple[Decimal, Decimal]:
    try:
        profile = account.owner.trading_profile
    except UserProfile.DoesNotExist:
        return _DEFAULT_MAX_DAILY_LOSS_PCT, _DEFAULT_MAX_POSITION_SIZE_PCT
    return profile.max_daily_loss_pct, profile.max_position_size_pct


def evaluate(
    account: Account,
    instrument: Instrument,
    side: Action,
    quantity: int,
    price: Decimal,
    strategy: Strategy | None = None,
) -> RiskCheckResult:
    max_daily_loss_pct, max_position_size_pct = _risk_profile(account)

    ok, reason = checks.check_max_daily_loss(account, max_daily_loss_pct)
    if ok:
        ok, reason = checks.check_max_position_size(
            account, instrument, side, quantity, price, max_position_size_pct
        )

    RiskDecision.objects.create(
        account=account,
        instrument=instrument,
        strategy=strategy,
        action=side.value,
        quantity=quantity,
        approved=ok,
        reason=reason,
    )
    return RiskCheckResult(approved=ok, reason=reason)
