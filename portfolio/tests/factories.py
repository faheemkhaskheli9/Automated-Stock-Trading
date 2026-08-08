from django.contrib.auth import get_user_model

from marketdata.models import Instrument
from portfolio.models import Account


def make_account(cash_balance=100_000, owner=None, **kwargs):
    User = get_user_model()
    owner = owner or User.objects.create_user(username=f"trader-{User.objects.count()}")
    return Account.objects.create(
        owner=owner, name="Test Account", cash_balance=cash_balance, **kwargs
    )


def make_instrument(symbol="ENGRO", **kwargs):
    return Instrument.objects.create(symbol=symbol, **kwargs)
