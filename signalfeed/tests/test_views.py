from datetime import date

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from signalfeed.models import WeeklySignal
from signalfeed.tests.factories import make_instrument

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user("op", password="pw")


def test_index_requires_login(client):
    resp = client.get(reverse("signalfeed:index"))
    assert resp.status_code == 302
    assert "/signals/login/" in resp.url or "login" in resp.url


def test_index_renders_with_signal(client, user):
    inst = make_instrument("ENGRO")
    WeeklySignal.objects.create(
        instrument=inst,
        as_of=date(2026, 2, 2),
        target_date=date(2026, 2, 6),
        direction=WeeklySignal.Direction.UP,
        expected_return_pct=2.5,
        predicted_close=110.0,
        reference_close=107.3,
        status=WeeklySignal.Status.SENT,
    )
    client.force_login(user)
    resp = client.get(reverse("signalfeed:index"))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "ENGRO" in body
    assert "Weekly signals" in body
    assert reverse("signalfeed:manifest") in body


def test_manifest_is_json(client):
    resp = client.get(reverse("signalfeed:manifest"))
    assert resp.status_code == 200
    assert resp["Content-Type"] == "application/manifest+json"
    assert resp.json()["short_name"] == "PSX Signals"
