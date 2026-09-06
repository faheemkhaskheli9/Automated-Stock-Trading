import pytest

from signalfeed import tasks
from signalfeed.tests.factories import (
    make_instrument,
    make_price_series,
    make_watch_item,
    make_weekly_model,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def watch():
    inst = make_instrument("ENGRO")
    make_price_series(inst, n=420)
    model = make_weekly_model([inst])
    make_watch_item(inst, model)
    return inst, model


def test_train_task_returns_run_ids(watch):
    ids = tasks.train_weekly_models_task()
    assert len(ids) == 1 and isinstance(ids[0], int)


def test_send_task_returns_json_safe_summary(watch, monkeypatch):
    monkeypatch.setattr("signalfeed.delivery.deliver", lambda s, m, channels=None: ["telegram"])
    summary = tasks.send_weekly_signals_task()
    assert "signals" not in summary
    assert summary["generated"] >= 1


def test_recap_task_runs(watch):
    summary = tasks.recap_weekly_signals_task()
    assert "window_hit_rate" in summary
