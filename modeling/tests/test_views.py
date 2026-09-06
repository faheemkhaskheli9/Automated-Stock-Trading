import pytest
from django.urls import reverse

from modeling.models import ModelTrainingRun, TradingModel
from modeling.tests.factories import make_instrument, make_price_series

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user("op", password="pw")


@pytest.fixture
def inst():
    obj = make_instrument("ENGRO")
    make_price_series(obj, n=320)
    return obj


def test_login_required(client):
    resp = client.get(reverse("modeling:index"))
    assert resp.status_code == 302 and "login" in resp["Location"]


def test_pages_render(client, user, inst):
    client.force_login(user)
    for name in ("modeling:index", "modeling:create", "modeling:estimators"):
        assert client.get(reverse(name)).status_code == 200


def test_create_train_predict_flow(client, user, inst):
    client.force_login(user)
    resp = client.post(
        reverse("modeling:create"),
        data={
            "name": "web model",
            "estimator": "ridge",
            "estimator_params": "",
            "ohlc_fields": ["open", "high", "low", "close"],
            "ohlc_lags": "0,1,2",
            "return_periods": "1,5",
            "feature_spec_json": "",
            "target_type": "horizon_close",
            "horizon": "1",
            "entry_weekday": "0",
            "exit_weekday": "4",
            "steps": "3",
            "instruments": [str(inst.pk)],
            "holdout_fraction": "0.2",
        },
    )
    assert resp.status_code == 302, getattr(resp, "context", None)
    model = TradingModel.objects.get()
    assert model.feature_spec[0]["kind"] == "ohlc"

    detail = reverse("modeling:detail", args=[model.pk])
    assert client.get(detail).status_code == 200

    assert client.post(detail, data={"action": "train"}).status_code == 302
    run = ModelTrainingRun.objects.get(model=model)
    assert run.status == ModelTrainingRun.Status.SUCCESS, run.error

    assert client.get(reverse("modeling:predict", args=[model.pk])).status_code == 200

    csv_resp = client.get(detail + "?export=csv")
    assert csv_resp["Content-Type"] == "text/csv"


def test_create_rejects_task_mismatch(client, user, inst):
    client.force_login(user)
    resp = client.post(
        reverse("modeling:create"),
        data={
            "name": "bad",
            "estimator": "logistic",
            "estimator_params": "",
            "ohlc_fields": ["close"],
            "ohlc_lags": "0",
            "feature_spec_json": "",
            "target_type": "horizon_close",
            "horizon": "1",
            "entry_weekday": "0",
            "exit_weekday": "4",
            "steps": "3",
            "instruments": [str(inst.pk)],
            "holdout_fraction": "0.2",
        },
    )
    assert resp.status_code == 200
    assert TradingModel.objects.count() == 0
