import pytest
from django.test import RequestFactory

from AutomaticStockTrading.scoping import scope_to_owner
from portfolio.models import Account

pytestmark = pytest.mark.django_db


def _request(user):
    req = RequestFactory().get("/")
    req.user = user
    return req


def test_scope_to_owner_filters_to_the_requesting_user(django_user_model):
    owner = django_user_model.objects.create_user("owner")
    other = django_user_model.objects.create_user("other")
    mine = Account.objects.create(owner=owner, name="Mine", cash_balance=1000)
    Account.objects.create(owner=other, name="Theirs", cash_balance=1000)

    qs = scope_to_owner(Account.objects.all(), _request(owner))
    assert list(qs) == [mine]


def test_scope_to_owner_lets_staff_see_everything(django_user_model):
    staff = django_user_model.objects.create_user("boss", is_staff=True)
    owner = django_user_model.objects.create_user("owner")
    Account.objects.create(owner=owner, name="Theirs", cash_balance=1000)

    qs = scope_to_owner(Account.objects.all(), _request(staff))
    assert qs.count() == 1


def test_scope_to_owner_supports_a_custom_lookup_path(django_user_model):
    """execution.Order / risk.RiskDecision scope through account__owner
    rather than a direct owner field."""
    from execution.models import Order
    from execution.tests.factories import make_instrument, make_order

    owner = django_user_model.objects.create_user("owner")
    other = django_user_model.objects.create_user("other")
    mine_acct = Account.objects.create(owner=owner, name="Mine", cash_balance=1000)
    theirs_acct = Account.objects.create(owner=other, name="Theirs", cash_balance=1000)
    inst = make_instrument("ENGRO")
    mine_order = make_order(mine_acct, inst)
    make_order(theirs_acct, inst)

    qs = scope_to_owner(Order.objects.all(), _request(owner), owner_lookup="account__owner")
    assert list(qs) == [mine_order]
