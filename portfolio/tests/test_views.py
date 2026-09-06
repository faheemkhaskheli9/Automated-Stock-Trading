import pytest
from django.urls import reverse

from portfolio.models import Account, Position

from .factories import make_instrument

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user("op", password="pw")


def make_account(*, owner, name="Acct", cash_balance=100_000, **kw):
    return Account.objects.create(owner=owner, name=name, cash_balance=cash_balance, **kw)


# --- list ----------------------------------------------------------
def test_account_list_requires_login(client):
    resp = client.get(reverse("portfolio:account_list"))
    assert resp.status_code == 302 and "login" in resp["Location"]


def test_account_list_is_owner_scoped(client, user, django_user_model):
    mine = make_account(owner=user, name="Mine")
    other = django_user_model.objects.create_user("other")
    make_account(owner=other, name="Theirs")
    client.force_login(user)
    resp = client.get(reverse("portfolio:account_list"))
    assert resp.status_code == 200
    assert b"Mine" in resp.content
    assert b"Theirs" not in resp.content
    assert list(r["obj"] for r in resp.context["rows"]) == [mine]


def test_staff_sees_all_accounts(client, django_user_model):
    staff = django_user_model.objects.create_user("boss", password="pw", is_staff=True)
    o1 = django_user_model.objects.create_user("o1")
    o2 = django_user_model.objects.create_user("o2")
    make_account(owner=o1, name="A1")
    make_account(owner=o2, name="A2")
    client.force_login(staff)
    resp = client.get(reverse("portfolio:account_list"))
    assert len(resp.context["rows"]) == 2


# --- detail ------------------------------------------------------
def test_account_detail_shows_positions(client, user):
    acct = make_account(owner=user, name="Mine", cash_balance=50_000)
    inst = make_instrument("ENGRO")
    Position.objects.create(account=acct, instrument=inst, quantity=10, avg_entry_price=100)
    client.force_login(user)
    resp = client.get(reverse("portfolio:account_detail", args=[acct.pk]))
    assert resp.status_code == 200
    assert b"ENGRO" in resp.content
    assert resp.context["positions"][0]["cost"] == 1000


def test_account_detail_404_for_other_owner(client, user, django_user_model):
    other = django_user_model.objects.create_user("other")
    acct = make_account(owner=other, name="Theirs")
    client.force_login(user)
    resp = client.get(reverse("portfolio:account_detail", args=[acct.pk]))
    assert resp.status_code == 404


# --- create / edit ---------------------------------------------
def test_create_account_sets_owner(client, user):
    client.force_login(user)
    resp = client.post(
        reverse("portfolio:account_create"),
        {
            "name": "Paper 1",
            "account_type": "paper",
            "broker": "paper",
            "currency": "PKR",
            "cash_balance": "100000",
        },
    )
    assert resp.status_code == 302
    acct = Account.objects.get(name="Paper 1")
    assert acct.owner == user


def test_create_account_rejects_duplicate_name(client, user):
    make_account(owner=user, name="Paper 1")
    client.force_login(user)
    resp = client.post(
        reverse("portfolio:account_create"),
        {
            "name": "Paper 1",
            "account_type": "paper",
            "broker": "paper",
            "currency": "PKR",
            "cash_balance": "1000",
        },
    )
    assert resp.status_code == 200
    assert Account.objects.filter(owner=user, name="Paper 1").count() == 1


def test_edit_account_changes_cash(client, user):
    acct = make_account(owner=user, name="Mine", cash_balance=100_000)
    client.force_login(user)
    resp = client.post(
        reverse("portfolio:account_edit", args=[acct.pk]),
        {
            "name": "Mine",
            "account_type": "paper",
            "broker": "paper",
            "currency": "PKR",
            "cash_balance": "250000",
        },
    )
    assert resp.status_code == 302
    acct.refresh_from_db()
    assert acct.cash_balance == 250_000
