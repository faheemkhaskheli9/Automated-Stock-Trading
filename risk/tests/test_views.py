import pytest
from django.urls import reverse

from portfolio.models import Account
from risk.models import DailyEquitySnapshot, RiskDecision

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user("op", password="pw")


def _account(owner, name="Acct"):
    return Account.objects.create(owner=owner, name=name, cash_balance=100_000)


def _instrument(symbol="ENGRO"):
    from marketdata.models import Instrument

    return Instrument.objects.create(symbol=symbol)


def test_decisions_requires_login(client):
    resp = client.get(reverse("risk:decisions"))
    assert resp.status_code == 302 and "login" in resp["Location"]


def test_decisions_owner_scoped(client, user, django_user_model):
    inst = _instrument()
    mine = _account(user, "Mine")
    theirs = _account(django_user_model.objects.create_user("other"), "Theirs")
    RiskDecision.objects.create(
        account=mine, instrument=inst, action="buy", quantity=1, approved=True
    )
    RiskDecision.objects.create(
        account=theirs, instrument=inst, action="buy", quantity=1, approved=False
    )
    client.force_login(user)
    resp = client.get(reverse("risk:decisions"))
    assert resp.status_code == 200
    assert list(resp.context["rows"]) == list(RiskDecision.objects.filter(account=mine))


def test_staff_sees_all_decisions(client, django_user_model):
    staff = django_user_model.objects.create_user("boss", password="pw", is_staff=True)
    inst = _instrument()
    a = _account(django_user_model.objects.create_user("u1"), "A")
    RiskDecision.objects.create(account=a, instrument=inst, action="buy", quantity=1, approved=True)
    client.force_login(staff)
    resp = client.get(reverse("risk:decisions"))
    assert len(resp.context["rows"]) == 1


def test_equity_snapshots_render(client, user):
    a = _account(user, "Mine")
    DailyEquitySnapshot.objects.create(account=a, date="2026-02-02", opening_equity=100_000)
    client.force_login(user)
    resp = client.get(reverse("risk:equity_snapshots"))
    assert resp.status_code == 200
    assert b"Mine" in resp.content
