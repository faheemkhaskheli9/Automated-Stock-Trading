import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from signalfeed.models import WatchItem
from signalfeed.tests.factories import (
    make_instrument,
    make_price_series,
    make_watch_item,
    make_weekly_model,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user("op", password="pw")


@pytest.fixture
def watched(db):
    inst = make_instrument("ENGRO")
    make_price_series(inst, n=420)
    model = make_weekly_model([inst])
    item = make_watch_item(inst, model)
    return inst, model, item


# --- watchlist listing ---------------------------------------------------
def test_watchlist_requires_login(client):
    resp = client.get(reverse("signalfeed:watchlist"))
    assert resp.status_code == 302
    assert "login" in resp.url


def test_watchlist_lists_items_with_gate(client, user, watched):
    _, model, _ = watched
    client.force_login(user)
    resp = client.get(reverse("signalfeed:watchlist"))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "ENGRO" in body
    assert model.name in body
    # a gate verdict is rendered (pass or blocked)
    assert "pass" in body or "blocked" in body


# --- create / edit / deactivate ---------------------------------------
def test_create_watch_item(client, user, db):
    inst = make_instrument("LUCK")
    make_price_series(inst, n=420)
    model = make_weekly_model([inst])
    client.force_login(user)
    resp = client.post(
        reverse("signalfeed:watch_create"),
        {
            "instrument": inst.pk,
            "trading_model": model.pk,
            "is_active": "on",
            "min_directional_accuracy": "0.55",
            "min_skill": "0.0",
            "min_expected_move_pct": "1.0",
            "notes": "",
        },
    )
    assert resp.status_code == 302
    assert WatchItem.objects.filter(instrument=inst, trading_model=model).exists()


def test_edit_watch_item(client, user, watched):
    inst, model, item = watched
    client.force_login(user)
    resp = client.post(
        reverse("signalfeed:watch_edit", args=[item.pk]),
        {
            "instrument": inst.pk,
            "trading_model": model.pk,
            "is_active": "on",
            "min_directional_accuracy": "0.70",
            "min_skill": "0.0",
            "min_expected_move_pct": "2.0",
            "notes": "tightened",
        },
    )
    assert resp.status_code == 302
    item.refresh_from_db()
    assert item.min_directional_accuracy == pytest.approx(0.70)
    assert item.min_expected_move_pct == pytest.approx(2.0)


def test_create_rejects_unsupported_target_model(client, user, db):
    inst = make_instrument("HBL")
    make_price_series(inst, n=420)
    model = make_weekly_model([inst], target={"type": "multistep", "steps": 3}, train=False)
    client.force_login(user)
    resp = client.post(
        reverse("signalfeed:watch_create"),
        {
            "instrument": inst.pk,
            "trading_model": model.pk,
            "min_directional_accuracy": "0.55",
            "min_skill": "0.0",
            "min_expected_move_pct": "1.0",
        },
    )
    assert resp.status_code == 200  # re-rendered with errors
    assert not WatchItem.objects.filter(instrument=inst).exists()


def test_deactivate_watch_item(client, user, watched):
    _, _, item = watched
    client.force_login(user)
    resp = client.post(reverse("signalfeed:watch_delete", args=[item.pk]))
    assert resp.status_code == 302
    item.refresh_from_db()
    assert item.is_active is False


# --- run actions -------------------------------------------------------
def test_run_requires_login(client):
    resp = client.post(reverse("signalfeed:run"), {"action": "send"})
    assert resp.status_code == 302
    assert "login" in resp.url


def test_run_unknown_action_redirects(client, user):
    client.force_login(user)
    resp = client.post(reverse("signalfeed:run"), {"action": "bogus"})
    assert resp.status_code == 302
    assert resp.url == reverse("signalfeed:index")


def test_run_send_action_delivers(client, user, monkeypatch):
    seen = {}

    def fake_send(as_of=None, *, dry_run=False, include_flat=False, channels=None):
        seen["dry_run"] = dry_run
        seen["include_flat"] = include_flat
        return {"generated": 2, "sent": 1, "suppressed": 1, "flat": 0, "errors": 0, "signals": []}

    monkeypatch.setattr("signalfeed.services.send_weekly_signals", fake_send)
    client.force_login(user)
    resp = client.post(reverse("signalfeed:run"), {"action": "send", "include_flat": "on"})
    assert resp.status_code == 302
    assert seen == {"dry_run": False, "include_flat": True}


def test_run_generate_action_is_dry(client, user, monkeypatch):
    seen = {}

    def fake_send(as_of=None, *, dry_run=False, include_flat=False, channels=None):
        seen["dry_run"] = dry_run
        return {"generated": 0, "sent": 0, "suppressed": 0, "flat": 0, "errors": 0, "signals": []}

    monkeypatch.setattr("signalfeed.services.send_weekly_signals", fake_send)
    client.force_login(user)
    resp = client.post(reverse("signalfeed:run"), {"action": "generate"})
    assert resp.status_code == 302
    assert seen["dry_run"] is True


def test_run_train_action(client, user, monkeypatch):
    monkeypatch.setattr("signalfeed.services.train_weekly_models", lambda: [])
    client.force_login(user)
    resp = client.post(reverse("signalfeed:run"), {"action": "train"})
    assert resp.status_code == 302
    assert resp.url == reverse("signalfeed:index")


def test_run_recap_action(client, user, monkeypatch):
    monkeypatch.setattr(
        "signalfeed.services.recap_weekly_signals",
        lambda as_of=None: {
            "scored_now": 0,
            "week_hits": 0,
            "week_total": 0,
            "delivered_to": [],
        },
    )
    client.force_login(user)
    resp = client.post(reverse("signalfeed:run"), {"action": "recap"})
    assert resp.status_code == 302
    assert resp.url == reverse("signalfeed:index")


def test_run_action_failure_is_surfaced(client, user, monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("kaboom")

    monkeypatch.setattr("signalfeed.services.recap_weekly_signals", boom)
    client.force_login(user)
    resp = client.post(reverse("signalfeed:run"), {"action": "recap"}, follow=True)
    assert resp.status_code == 200
    assert b"kaboom" in resp.content
