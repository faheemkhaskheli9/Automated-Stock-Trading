from portfolio.tests.factories import make_account, make_instrument

from ..models import Order

__all__ = ["make_account", "make_instrument", "make_order"]


def make_order(account, instrument, side=Order.Side.BUY, quantity=10, **kwargs):
    return Order.objects.create(
        account=account, instrument=instrument, side=side, quantity=quantity, **kwargs
    )
