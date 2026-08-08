"""Individual pre-trade risk checks. Each returns (ok, reason) - `reason`
is empty when ok, otherwise explains the rejection for the RiskDecision
audit log (see engine.py)."""

from decimal import Decimal

from django.utils import timezone

from marketdata.models import Instrument
from portfolio.models import Account, Position
from strategies.signals import Action

from .models import DailyEquitySnapshot


def get_opening_equity(account: Account, day=None) -> Decimal:
    """The account's equity as of the first check today - created lazily
    on first use rather than by a separate scheduled job, so this works
    correctly even if nothing runs before market open on a given day."""
    day = day or timezone.localdate()
    snapshot, _ = DailyEquitySnapshot.objects.get_or_create(
        account=account, date=day, defaults={"opening_equity": account.equity}
    )
    return snapshot.opening_equity


def check_max_daily_loss(account: Account, max_daily_loss_pct: Decimal) -> tuple[bool, str]:
    opening = get_opening_equity(account)
    if opening <= 0:
        return True, ""

    current = account.equity
    loss_pct = (opening - current) / opening * 100
    if loss_pct >= max_daily_loss_pct:
        return False, f"daily loss {loss_pct:.2f}% has reached the {max_daily_loss_pct}% limit"
    return True, ""


def check_max_position_size(
    account: Account,
    instrument: Instrument,
    side: Action,
    quantity: int,
    price: Decimal,
    max_position_size_pct: Decimal,
) -> tuple[bool, str]:
    if side == Action.SELL:
        return True, ""  # selling only reduces exposure

    equity = account.equity
    if equity <= 0:
        return False, "account has no equity"

    existing = Position.objects.filter(account=account, instrument=instrument).first()
    existing_value = existing.quantity * price if existing else Decimal("0")
    new_value = existing_value + quantity * price
    max_allowed = equity * max_position_size_pct / 100

    if new_value > max_allowed:
        return (
            False,
            f"position value {new_value:.2f} would exceed {max_position_size_pct}% of equity "
            f"({max_allowed:.2f})",
        )
    return True, ""
