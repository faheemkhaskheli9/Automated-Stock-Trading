"""Broker adapter interface.

PSX has no public self-serve order-routing API (see docs/PLAN.md) - the
only concrete implementation right now is PaperBroker (paper.py), which
simulates fills against stored market data. A real PSX adapter (via a
vendor like StockIntel, or a direct broker relationship) is a drop-in
later: implement this interface, register it in `get_broker`, point an
Account at it.
"""

from abc import ABC, abstractmethod

from portfolio.models import Account, Position

from ..models import Order


class BrokerAdapter(ABC):
    @abstractmethod
    def submit_order(self, order: Order) -> Order:
        """Submit `order` for execution. Mutates and returns it with the
        resulting status (SUBMITTED/FILLED/REJECTED) and fill details."""

    @abstractmethod
    def cancel_order(self, order: Order) -> Order:
        """Cancel `order` if it's still cancellable. Mutates and returns it."""

    @abstractmethod
    def get_positions(self, account: Account) -> list[Position]:
        """Current positions for `account`, per this broker's records."""

    @abstractmethod
    def get_account(self, account: Account) -> Account:
        """Refresh and return `account`'s broker-side state (e.g. cash balance)."""
