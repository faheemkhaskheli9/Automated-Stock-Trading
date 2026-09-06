from datetime import datetime, timezone
from decimal import Decimal

import pytest
from django.urls import reverse

from marketdata.models import PriceBar

from ..models import Order
from .factories import make_account, make_instrument, make_order

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user("op", password="pw")


def _bar(instrument, close=Decimal("10")):
    return PriceBar.objects.create(
        instrument=instrument,
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        open=close,
        high=close,
        low=close,
        close=close,
        volume=1000,
    )


# --- order list / detail ------------------------------------------
def test_order_list_requires_login(client):
    resp = client.get(reverse("execution:order_list"))
    assert resp.status_code == 302 and "login" in resp["Location"]


def test_order_list_is_owner_scoped(client, user, django_user_model):
    mine = make_account(owner=user)
    other = make_account(owner=django_user_model.objects.create_user("other"))
    inst = make_instrument("ENGRO")
    make_order(mine, inst)
    make_order(other, inst)
    client.force_login(user)
    resp = client.get(reverse("execution:order_list"))
    assert resp.status_code == 200
    assert list(resp.context["orders"]) == list(Order.objects.filter(account=mine))
    assert resp.context["can_run_cycle"] is False


def test_order_detail_404_for_other_owner(client, user, django_user_model):
    other = make_account(owner=django_user_model.objects.create_user("other"))
    order = make_order(other, make_instrument("ENGRO"))
    client.force_login(user)
    resp = client.get(reverse("execution:order_detail", args=[order.pk]))
    assert resp.status_code == 404


# --- place order -------------------------------------------------
def test_place_order_get_renders(client, user):
    make_account(owner=user)
    client.force_login(user)
    resp = client.get(reverse("execution:place_order"))
    assert resp.status_code == 200
    assert b"Place a paper order" in resp.content


def test_place_order_fills(client, user):
    account = make_account(owner=user, cash_balance=100_000)
    inst = make_instrument("ENGRO")
    _bar(inst)
    client.force_login(user)
    resp = client.post(
        reverse("execution:place_order"),
        {
            "account": account.pk,
            "instrument": inst.pk,
            "side": "buy",
            "quantity": "10",
            "confirm": "on",
        },
    )
    assert resp.status_code == 302
    order = Order.objects.get(account=account)
    assert order.status == Order.Status.FILLED
    assert resp.url == reverse("execution:order_detail", args=[order.pk])


def test_place_order_requires_confirm(client, user):
    account = make_account(owner=user)
    inst = make_instrument("ENGRO")
    _bar(inst)
    client.force_login(user)
    resp = client.post(
        reverse("execution:place_order"),
        {"account": account.pk, "instrument": inst.pk, "side": "buy", "quantity": "10"},
    )
    assert resp.status_code == 200
    assert not Order.objects.exists()


def test_place_order_rejects_non_paper_account(client, user):
    account = make_account(owner=user)
    from portfolio.models import Account

    Account.objects.filter(pk=account.pk).update(broker="live")
    inst = make_instrument("ENGRO")
    _bar(inst)
    client.force_login(user)
    resp = client.post(
        reverse("execution:place_order"),
        {
            "account": account.pk,
            "instrument": inst.pk,
            "side": "buy",
            "quantity": "10",
            "confirm": "on",
        },
    )
    assert resp.status_code == 200
    assert not Order.objects.exists()


def test_place_order_other_users_account_is_not_a_choice(client, user, django_user_model):
    other_acct = make_account(owner=django_user_model.objects.create_user("other"))
    inst = make_instrument("ENGRO")
    _bar(inst)
    client.force_login(user)
    resp = client.post(
        reverse("execution:place_order"),
        {
            "account": other_acct.pk,
            "instrument": inst.pk,
            "side": "buy",
            "quantity": "10",
            "confirm": "on",
        },
    )
    assert resp.status_code == 200
    assert not Order.objects.exists()


# --- run cycle -------------------------------------------------
def test_run_cycle_requires_staff(client, user, monkeypatch):
    called = {"n": 0}
    monkeypatch.setattr(
        "execution.views.run_trading_cycle", lambda: called.__setitem__("n", 1) or []
    )
    client.force_login(user)
    resp = client.post(reverse("execution:run_cycle"), {"confirm": "yes"})
    assert resp.status_code == 302
    assert called["n"] == 0


def test_run_cycle_staff_runs(client, django_user_model, monkeypatch):
    staff = django_user_model.objects.create_user("boss", password="pw", is_staff=True)
    monkeypatch.setattr("execution.views.run_trading_cycle", lambda: [1, 2, 3])
    client.force_login(staff)
    resp = client.post(reverse("execution:run_cycle"), {"confirm": "yes"}, follow=True)
    assert resp.status_code == 200
    assert b"placed 3 order(s)" in resp.content


def test_run_cycle_requires_login(client):
    resp = client.post(reverse("execution:run_cycle"), {"confirm": "yes"})
    assert resp.status_code == 302 and "login" in resp["Location"]
