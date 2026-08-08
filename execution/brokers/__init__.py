from portfolio.models import Account

from .base import BrokerAdapter
from .paper import PaperBroker

__all__ = ["BrokerAdapter", "PaperBroker", "get_broker"]

_BROKERS: dict[str, type[BrokerAdapter]] = {
    Account.Broker.PAPER: PaperBroker,
}


def get_broker(account: Account) -> BrokerAdapter:
    try:
        return _BROKERS[account.broker]()
    except KeyError:
        raise ValueError(f"No BrokerAdapter registered for broker={account.broker!r}") from None
