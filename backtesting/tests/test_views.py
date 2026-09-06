import pytest
from django.urls import reverse

from backtesting.models import Backtest, BacktestRun
from backtesting.tests.factories import (
    make_instrument,
    make_price_series,
    make_trading_model,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user("op", password="pw")


@pytest.fixture
def model():
    inst = make_instrument("ENGRO")
    make_price_series(inst, n=420)
    return make_trading_model([inst], estimator_key="ridge")


def test_login_required(client):
    resp = client.get(reverse("backtesting:index"))
    assert resp.status_code == 302 and "login" in resp["Location"]


def test_pages_render(client, user, model):
    client.force_login(user)
    assert client.get(reverse("backtesting:index")).status_code == 200
    assert client.get(reverse("backtesting:create")).status_code == 200


def test_create_and_run_flow(client, user, model):
    client.force_login(user)
    resp = client.post(
        reverse("backtesting:create"),
        data={
            "name": "web bt",
            "model": str(model.pk),
            "scheme": "expanding",
            "train_span": "120",
            "test_span": "20",
            "step": "20",
            "gap": "1",
            "long_threshold": "0.0",
            "initial_cash": "100000",
            "commission_bps": "0",
            "slippage_bps": "0",
        },
    )
    assert resp.status_code == 302, getattr(resp, "context", None)
    bt = Backtest.objects.get()

    detail = reverse("backtesting:detail", args=[bt.pk])
    assert client.get(detail).status_code == 200

    assert client.post(detail, data={"action": "run"}).status_code == 302
    run = BacktestRun.objects.get(backtest=bt)
    assert run.status == BacktestRun.Status.SUCCESS, run.error

    assert client.get(detail).status_code == 200
    csv_resp = client.get(detail + "?export=csv")
    assert csv_resp["Content-Type"] == "text/csv"


def test_create_rejects_unsupported_target(client, user):
    inst = make_instrument("LUCK")
    make_price_series(inst, n=200)
    # every real modeling target is backtestable now; the SUPPORTED_TARGETS
    # gate still rejects a target type this app has no handler for.
    bad_model = make_trading_model([inst], target={"type": "somethingelse"})
    client.force_login(user)
    resp = client.post(
        reverse("backtesting:create"),
        data={
            "name": "bad",
            "model": str(bad_model.pk),
            "scheme": "expanding",
            "train_span": "120",
            "test_span": "20",
            "step": "20",
            "gap": "1",
            "long_threshold": "0.0",
            "initial_cash": "100000",
            "commission_bps": "0",
            "slippage_bps": "0",
        },
    )
    assert resp.status_code == 200
    assert Backtest.objects.count() == 0
