"""Dashboard D7 - the strict-path forecast backtest runner UI.

Covers the login gate, the config form, the synchronous run-and-persist POST
flow, the rendered detail page (fold table + skill + charts), CSV export and
the never-raises failure path surfaced as a message.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pytest
from django.urls import reverse

from forecasting.models import ForecastBacktestRun
from research.tests.factories import make_instrument, make_price_series

pytestmark = pytest.mark.django_db

ZONE = ZoneInfo("Asia/Karachi")


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user("op", password="pw")


@pytest.fixture
def history():
    inst = make_instrument("ENGRO")
    rng = np.random.default_rng(7)
    closes = np.abs(100.0 + np.cumsum(rng.normal(0.1, 0.8, 44))) + 40.0
    make_price_series(inst, list(closes), start=datetime(2026, 1, 1, tzinfo=ZONE))
    return inst


def _form_data(**overrides):
    data = {
        "name": "web run",
        "predictor_key": "naive",
        "symbol": "ENGRO",
        "params": "{}",
        "providers": "none",
        "scheme": "expanding",
        "train_span": "15",
        "test_span": "5",
        "step": "5",
        "gap": "1",
        "start": "2026-01-01",
        "end": "2026-02-20",
        "long_threshold": "0.0",
        "cost_bps": "0.0",
        "initial_cash": "100000",
    }
    data.update(overrides)
    return data


# --------------------------------------------------------------------------- #
# auth
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name", ["index", "create"])
def test_login_required(client, name):
    resp = client.get(reverse(f"forecasting:{name}"))
    assert resp.status_code == 302 and "login" in resp["Location"]


def test_detail_login_required(client, history):
    run = ForecastBacktestRun.objects.create(
        predictor_key="naive", symbol="ENGRO", start="2026-01-01", end="2026-02-01"
    )
    resp = client.get(reverse("forecasting:detail", args=[run.pk]))
    assert resp.status_code == 302 and "login" in resp["Location"]


# --------------------------------------------------------------------------- #
# pages render
# --------------------------------------------------------------------------- #
def test_index_and_form_render(client, user, history):
    client.force_login(user)
    assert client.get(reverse("forecasting:index")).status_code == 200
    form_page = client.get(reverse("forecasting:create"))
    assert form_page.status_code == 200
    assert b"ENGRO" in form_page.content  # symbol choice populated from PSX instruments


# --------------------------------------------------------------------------- #
# run + persist flow
# --------------------------------------------------------------------------- #
def test_run_flow_persists_and_redirects_to_detail(client, user, history):
    client.force_login(user)
    resp = client.post(reverse("forecasting:create"), data=_form_data(), follow=True)
    assert resp.status_code == 200

    run = ForecastBacktestRun.objects.get()
    assert run.status == ForecastBacktestRun.Status.SUCCESS
    assert run.created_by_id == user.pk
    assert run.n_folds == 5
    assert run.n_predictions == 25
    assert run.provider_keys == []

    assert resp.redirect_chain[-1][0].endswith(f"/forecast-backtests/{run.pk}/")
    body = resp.content.decode()
    assert "Aggregate" in body
    assert "Skill vs naive" in body
    assert "Folds" in body


def test_invalid_params_json_is_rejected(client, user, history):
    client.force_login(user)
    resp = client.post(reverse("forecasting:create"), data=_form_data(params="{not json"))
    assert resp.status_code == 200
    assert not ForecastBacktestRun.objects.exists()
    assert "valid JSON" in resp.content.decode()


def test_end_before_start_is_rejected(client, user, history):
    client.force_login(user)
    resp = client.post(
        reverse("forecasting:create"),
        data=_form_data(start="2026-02-20", end="2026-01-01"),
    )
    assert resp.status_code == 200
    assert not ForecastBacktestRun.objects.exists()


def test_history_too_short_records_failed_run_and_shows_message(client, user, history):
    client.force_login(user)
    resp = client.post(
        reverse("forecasting:create"),
        data=_form_data(train_span="400"),
        follow=True,
    )
    run = ForecastBacktestRun.objects.get()
    assert run.status == ForecastBacktestRun.Status.FAILED
    assert "history too short" in run.error
    assert "failed" in resp.content.decode().lower()


# --------------------------------------------------------------------------- #
# CSV export
# --------------------------------------------------------------------------- #
def test_predictions_csv_export(client, user, history):
    client.force_login(user)
    client.post(reverse("forecasting:create"), data=_form_data())
    run = ForecastBacktestRun.objects.get()

    resp = client.get(reverse("forecasting:detail", args=[run.pk]), {"export": "csv"})
    assert resp.status_code == 200
    assert resp["Content-Type"] == "text/csv"
    lines = resp.content.decode().splitlines()
    assert lines[0] == "fold,as_of,target_date,anchor,predicted,actual"
    assert len(lines) == 1 + run.n_predictions
