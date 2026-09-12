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


def test_account_list_positions_count_is_correct(client, user):
    acct1 = make_account(owner=user, name="A1")
    acct2 = make_account(owner=user, name="A2")
    inst1 = make_instrument("ENGRO")
    inst2 = make_instrument("LUCK")
    Position.objects.create(account=acct1, instrument=inst1, quantity=10, avg_entry_price=100)
    Position.objects.create(account=acct1, instrument=inst2, quantity=5, avg_entry_price=50)
    Position.objects.create(account=acct2, instrument=inst1, quantity=1, avg_entry_price=100)
    client.force_login(user)

    resp = client.get(reverse("portfolio:account_list"))
    counts = {r["obj"].name: r["positions"] for r in resp.context["rows"]}
    assert counts == {"A1": 2, "A2": 1}


def test_account_list_query_count_does_not_scale_with_account_count(client, user, monkeypatch):
    """Regression test: account_list must report each account's position
    count from the already-prefetched queryset (len()), not with a fresh
    COUNT(*) per account - otherwise the query count grows with the number
    of accounts on the page. `equity` is stubbed out here since it issues
    its own per-account query independent of this fix (a separate, known
    inefficiency not covered by this regression test)."""
    from decimal import Decimal

    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    monkeypatch.setattr(Account, "equity", property(lambda self: Decimal("0")))
    inst = make_instrument("ENGRO")

    def _query_count(n_accounts):
        for i in range(n_accounts):
            acct = make_account(owner=user, name=f"Acct{i}")
            Position.objects.create(account=acct, instrument=inst, quantity=1, avg_entry_price=1)
        client.force_login(user)
        with CaptureQueriesContext(connection) as ctx:
            client.get(reverse("portfolio:account_list"))
        return len(ctx)

    few = _query_count(2)
    Account.objects.all().delete()
    many = _query_count(8)
    assert few == many


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


def test_staff_edit_checks_uniqueness_against_actual_owner(client, django_user_model):
    """A staff user editing someone else's account must have the name check
    run against that account's owner, not the staff user's own accounts -
    otherwise a rename can collide with another of the target owner's
    accounts and blow up the DB's unique-together constraint."""
    staff = django_user_model.objects.create_user("boss", password="pw", is_staff=True)
    target = django_user_model.objects.create_user("target")
    make_account(owner=target, name="Existing")
    acct = make_account(owner=target, name="ToRename")
    client.force_login(staff)
    resp = client.post(
        reverse("portfolio:account_edit", args=[acct.pk]),
        {
            "name": "Existing",  # collides with target's other account
            "account_type": "paper",
            "broker": "paper",
            "currency": "PKR",
            "cash_balance": "1000",
        },
    )
    # Caught as a normal form validation error, not an unhandled IntegrityError.
    assert resp.status_code == 200
    assert "already have an account with this name" in resp.content.decode()
    acct.refresh_from_db()
    assert acct.name == "ToRename"


def test_staff_edit_allows_name_matching_staffs_own_account(client, django_user_model):
    """The uniqueness check must not accidentally reject a name just because
    the staff user (not the account's owner) happens to have that name too."""
    staff = django_user_model.objects.create_user("boss", password="pw", is_staff=True)
    make_account(owner=staff, name="Shared Name")
    target = django_user_model.objects.create_user("target")
    acct = make_account(owner=target, name="ToRename")
    client.force_login(staff)
    resp = client.post(
        reverse("portfolio:account_edit", args=[acct.pk]),
        {
            "name": "Shared Name",
            "account_type": "paper",
            "broker": "paper",
            "currency": "PKR",
            "cash_balance": "1000",
        },
    )
    assert resp.status_code == 302
    acct.refresh_from_db()
    assert acct.name == "Shared Name"
