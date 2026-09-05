import pytest
from django.urls import reverse

from modeling.tests.factories import make_instrument, make_price_series

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user("op", password="pw")


@pytest.fixture
def inst():
    obj = make_instrument("ENGRO")
    make_price_series(obj, n=120)
    return obj


def _form_data(inst, **overrides):
    data = {
        "instrument": str(inst.pk),
        "model": "ma_crossover",
        "start": "",
        "end": "",
        "initial_cash": "100000",
        "commission_bps": "10",
        "slippage_bps": "5",
        "fast_period": "5",
        "slow_period": "20",
    }
    data.update(overrides)
    return data


def test_login_required(client):
    resp = client.get(reverse("strategies:backtest"))
    assert resp.status_code == 302 and "login" in resp["Location"]


def test_get_renders_empty_state(client, user):
    client.force_login(user)
    resp = client.get(reverse("strategies:backtest"))
    assert resp.status_code == 200
    assert b"Configure a backtest" in resp.content
    assert b"Backtest results" not in resp.content


def test_post_runs_a_backtest_and_renders_results(client, user, inst):
    client.force_login(user)
    resp = client.post(reverse("strategies:backtest"), data=_form_data(inst))
    assert resp.status_code == 200
    assert resp.context["result"] is not None
    assert resp.context["instrument"] == inst
    assert b"Equity curve" in resp.content


def test_post_export_csv_returns_a_download(client, user, inst):
    client.force_login(user)
    resp = client.post(reverse("strategies:backtest"), data=_form_data(inst, export="csv"))
    assert resp["Content-Type"] == "text/csv"
    assert "attachment" in resp["Content-Disposition"]
    assert resp.content.splitlines()[0].startswith(b"entry_date,exit_date,shares")


def test_post_with_too_little_history_shows_a_form_error(client, user):
    thin = make_instrument("THIN")
    make_price_series(thin, n=2)
    client.force_login(user)
    resp = client.post(reverse("strategies:backtest"), data=_form_data(thin))
    assert resp.status_code == 200
    assert resp.context.get("result") is None
    assert b"three daily bars" in resp.content


def test_saved_strategies_are_hidden_without_permission(client, user, inst):
    client.force_login(user)
    resp = client.get(reverse("strategies:backtest"))
    choices = dict(resp.context["form"].fields["model"].choices)
    assert not any(str(k).startswith("saved:") for k in choices)
