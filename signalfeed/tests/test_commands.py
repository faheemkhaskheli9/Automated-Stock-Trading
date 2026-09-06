from datetime import date
from io import StringIO

import pytest
from django.core.management import call_command

from signalfeed.models import WeeklySignal
from signalfeed.tests.factories import (
    make_instrument,
    make_price_series,
    make_watch_item,
    make_weekly_model,
)

pytestmark = pytest.mark.django_db
MON = date(2026, 2, 2)


@pytest.fixture
def watch():
    inst = make_instrument("ENGRO")
    make_price_series(inst, n=420)
    model = make_weekly_model([inst])
    make_watch_item(inst, model)
    return inst, model


def test_send_weekly_signals_dry_run(watch, monkeypatch):
    monkeypatch.setattr(
        "signalfeed.delivery.deliver", lambda *a, **k: pytest.fail("dry run must not deliver")
    )
    out = StringIO()
    call_command("send_weekly_signals", "--as-of", "2026-02-02", "--dry-run", stdout=out)
    assert "generated=1" in out.getvalue()
    assert WeeklySignal.objects.get().status == WeeklySignal.Status.PENDING


def test_send_weekly_signals_delivers(watch, monkeypatch):
    monkeypatch.setattr("signalfeed.delivery.deliver", lambda s, m, channels=None: ["telegram"])
    out = StringIO()
    call_command("send_weekly_signals", "--as-of", "2026-02-02", stdout=out)
    assert "sent=1" in out.getvalue()


def test_train_weekly_models_command(watch):
    out = StringIO()
    call_command("train_weekly_models", stdout=out)
    assert "success" in out.getvalue().lower()


def test_recap_weekly_signals_command(watch, monkeypatch):
    monkeypatch.setattr("signalfeed.delivery.deliver", lambda s, m, channels=None: ["email"])
    monkeypatch.setattr("signalfeed.services.deliver_signal", lambda sig, channels=None: ["email"])
    call_command("send_weekly_signals", "--as-of", "2026-02-02")
    WeeklySignal.objects.update(status=WeeklySignal.Status.SENT)
    out = StringIO()
    call_command("recap_weekly_signals", "--as-of", "2026-02-09", stdout=out)
    assert "scored_now=1" in out.getvalue()
