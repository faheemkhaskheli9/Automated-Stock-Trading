import json

import pytest
from django.urls import reverse

from modeling.models import TradingModel
from modelsearch.models import ModelSearch, ModelSearchResult
from modelsearch.tests.factories import (
    make_base_model,
    make_instrument,
    make_price_series,
    make_search,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user("op", password="pw")


@pytest.fixture
def inst():
    obj = make_instrument("ENGRO")
    make_price_series(obj, n=330)
    return obj


def test_login_required(client):
    resp = client.get(reverse("modelsearch:index"))
    assert resp.status_code == 302 and "login" in resp["Location"]


def test_pages_render(client, user, inst):
    client.force_login(user)
    assert client.get(reverse("modelsearch:index")).status_code == 200
    assert client.get(reverse("modelsearch:create")).status_code == 200


def test_create_prefills_from_base_model(client, user, inst):
    client.force_login(user)
    base = make_base_model([inst])
    resp = client.get(reverse("modelsearch:create") + f"?from={base.pk}")
    assert resp.status_code == 200
    assert b"horizon_close" in resp.content


def test_create_and_run_and_promote_flow(client, user, inst):
    client.force_login(user)
    base = make_base_model([inst])
    resp = client.post(
        reverse("modelsearch:create"),
        data={
            "name": "web sweep",
            "feature_spec_json": json.dumps(base.feature_spec),
            "target_spec_json": json.dumps(base.target_spec),
            "instruments": [str(inst.pk)],
            "holdout_fraction": "0.2",
            "estimators": ["ridge", "random_forest"],
            "param_grids_json": json.dumps({"ridge": {"alpha": [0.5, 1.0]}}),
            "mode": "grid",
            "max_candidates": "40",
            "random_seed": "0",
            "scoring": "",
        },
    )
    assert resp.status_code == 302, resp.context["form"].errors if resp.context else resp
    search = ModelSearch.objects.get()

    run_resp = client.post(reverse("modelsearch:detail", args=[search.pk]), data={"action": "run"})
    assert run_resp.status_code == 302
    assert ModelSearchResult.objects.filter(search=search, status="ok").exists()

    best = ModelSearchResult.objects.filter(search=search, rank=1).get()
    promote_resp = client.post(
        reverse("modelsearch:detail", args=[search.pk]),
        data={"action": "promote", "result": str(best.pk)},
    )
    assert promote_resp.status_code == 302
    assert "/modeling/" in promote_resp["Location"]
    assert TradingModel.objects.filter(estimator_key=best.estimator_key).count() >= 1


def test_detail_renders_results(client, user, inst):
    client.force_login(user)
    search = make_search([inst])
    client.post(reverse("modelsearch:detail", args=[search.pk]), data={"action": "run"})
    resp = client.get(reverse("modelsearch:detail", args=[search.pk]))
    assert resp.status_code == 200
    assert b"Candidates" in resp.content
