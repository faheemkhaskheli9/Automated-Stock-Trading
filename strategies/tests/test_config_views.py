import pytest
from django.urls import reverse

from modeling.tests.factories import make_instrument
from strategies.models import ManualSignal, Strategy

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user("op", password="pw")


@pytest.fixture
def inst():
    return make_instrument("ENGRO")


# --- Strategy config -------------------------------------------------
def test_strategy_list_requires_login(client):
    resp = client.get(reverse("strategies:strategy_list"))
    assert resp.status_code == 302 and "login" in resp["Location"]


def test_strategy_list_renders(client, user):
    Strategy.objects.create(name="RSI daily", key="rsi")
    client.force_login(user)
    resp = client.get(reverse("strategies:strategy_list"))
    assert resp.status_code == 200
    assert b"RSI daily" in resp.content


def test_create_strategy(client, user):
    client.force_login(user)
    resp = client.post(
        reverse("strategies:strategy_create"),
        {"name": "RSI daily", "key": "rsi", "params": "{}", "is_active": ""},
    )
    assert resp.status_code == 302
    s = Strategy.objects.get(name="RSI daily")
    assert s.key == "rsi" and s.params == {}


def test_create_strategy_rejects_unknown_key(client, user):
    client.force_login(user)
    resp = client.post(
        reverse("strategies:strategy_create"),
        {"name": "bogus", "key": "does_not_exist", "params": "{}"},
    )
    assert resp.status_code == 200
    assert not Strategy.objects.filter(name="bogus").exists()


def test_create_strategy_rejects_bad_params_json(client, user):
    client.force_login(user)
    resp = client.post(
        reverse("strategies:strategy_create"),
        {"name": "RSI daily", "key": "rsi", "params": "not json"},
    )
    assert resp.status_code == 200
    assert not Strategy.objects.filter(name="RSI daily").exists()


def test_edit_strategy(client, user):
    s = Strategy.objects.create(name="old", key="rsi")
    client.force_login(user)
    resp = client.post(
        reverse("strategies:strategy_edit", args=[s.pk]),
        {"name": "new name", "key": "rsi", "params": "{}"},
    )
    assert resp.status_code == 302
    s.refresh_from_db()
    assert s.name == "new name"


def test_toggle_strategy(client, user):
    s = Strategy.objects.create(name="RSI", key="rsi", is_active=False)
    client.force_login(user)
    resp = client.post(reverse("strategies:strategy_toggle", args=[s.pk]))
    assert resp.status_code == 302
    s.refresh_from_db()
    assert s.is_active is True


def test_toggle_requires_login(client):
    s = Strategy.objects.create(name="RSI", key="rsi")
    resp = client.post(reverse("strategies:strategy_toggle", args=[s.pk]))
    assert resp.status_code == 302 and "login" in resp["Location"]


# --- Manual signals -------------------------------------------------
def test_manual_list_renders(client, user, inst):
    ManualSignal.objects.create(instrument=inst, date="2026-02-02", action="buy")
    client.force_login(user)
    resp = client.get(reverse("strategies:manual_list"))
    assert resp.status_code == 200
    assert b"ENGRO" in resp.content


def test_create_manual_signal_sets_created_by(client, user, inst):
    client.force_login(user)
    resp = client.post(
        reverse("strategies:manual_create"),
        {"instrument": inst.pk, "date": "2026-02-02", "action": "buy", "note": ""},
    )
    assert resp.status_code == 302
    sig = ManualSignal.objects.get(instrument=inst)
    assert sig.created_by == user and sig.action == "buy"


def test_manual_signal_duplicate_date_is_rejected(client, user, inst):
    ManualSignal.objects.create(instrument=inst, date="2026-02-02", action="buy")
    client.force_login(user)
    resp = client.post(
        reverse("strategies:manual_create"),
        {"instrument": inst.pk, "date": "2026-02-02", "action": "sell", "note": ""},
    )
    assert resp.status_code == 200
    assert ManualSignal.objects.filter(instrument=inst).count() == 1


def test_manual_edit_changes_action(client, user, inst):
    sig = ManualSignal.objects.create(instrument=inst, date="2026-02-02", action="buy")
    client.force_login(user)
    resp = client.post(
        reverse("strategies:manual_edit", args=[sig.pk]),
        {"instrument": inst.pk, "date": "2026-02-02", "action": "sell", "note": "flip"},
    )
    assert resp.status_code == 302
    sig.refresh_from_db()
    assert sig.action == "sell"
