from datetime import date, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from modeling.models import ModelPrediction, ModelTrainingRun, TradingModel
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


def test_index_paginates_and_clamps_out_of_range_page(client, user, inst):
    from modeling.views import MODEL_PAGE_SIZE

    for i in range(MODEL_PAGE_SIZE + 3):
        TradingModel.objects.create(
            name=f"m-{i}",
            estimator_key="ridge",
            target_spec={"type": "horizon_close", "horizon": 1},
        )
    client.force_login(user)

    page1 = client.get(reverse("modeling:index"))
    assert page1.status_code == 200
    assert page1.context["page"].number == 1
    assert page1.context["page"].paginator.count == MODEL_PAGE_SIZE + 3

    # An out-of-range page number clamps to the last page rather than 404ing.
    far = client.get(reverse("modeling:index"), {"page": "999"})
    assert far.status_code == 200
    assert far.context["page"].number == far.context["page"].paginator.num_pages

    # A non-numeric page falls back to page 1 rather than erroring.
    bad = client.get(reverse("modeling:index"), {"page": "not-a-number"})
    assert bad.status_code == 200
    assert bad.context["page"].number == 1


def test_detail_paginates_predictions_and_page_one_matches_chart_head(client, user, inst):
    from modeling.views import PREDICTION_PAGE_SIZE

    model = TradingModel.objects.create(
        name="pred-model",
        estimator_key="ridge",
        target_spec={"type": "horizon_close", "horizon": 1},
    )
    model.instruments.add(inst)
    ModelPrediction.objects.bulk_create(
        ModelPrediction(
            model=model,
            instrument=inst,
            as_of=timezone.now(),
            target_date=date(2025, 1, 1) + timedelta(days=i),
            predicted_value=100.0 + i,
        )
        for i in range(PREDICTION_PAGE_SIZE + 5)
    )
    client.force_login(user)
    detail = reverse("modeling:detail", args=[model.pk])

    page1 = client.get(detail)
    assert page1.status_code == 200
    assert page1.context["prediction_page"].number == 1
    assert page1.context["prediction_page"].paginator.count == PREDICTION_PAGE_SIZE + 5
    # Page 1's rows are the head of the chart/CSV `predictions` list (same
    # ordering, most-recent target_date first).
    assert (
        list(page1.context["prediction_page"].object_list)
        == page1.context["predictions"][:PREDICTION_PAGE_SIZE]
    )

    page2 = client.get(detail, {"page": "2"})
    assert page2.status_code == 200
    assert page2.context["prediction_page"].number == 2

    far = client.get(detail, {"page": "999"})
    assert far.status_code == 200
    assert (
        far.context["prediction_page"].number == far.context["prediction_page"].paginator.num_pages
    )


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
