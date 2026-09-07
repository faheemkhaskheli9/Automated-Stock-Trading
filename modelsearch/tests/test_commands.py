from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from modelsearch.models import ModelSearchRun
from modelsearch.tests.factories import make_instrument, make_price_series, make_search

pytestmark = pytest.mark.django_db


@pytest.fixture
def inst():
    obj = make_instrument("ENGRO")
    make_price_series(obj, n=330)
    return obj


def test_run_model_search_command(inst):
    search = make_search([inst])
    out = StringIO()
    call_command("run_model_search", str(search.pk), "--max", "5", stdout=out)
    assert "scored" in out.getvalue()
    run = ModelSearchRun.objects.filter(search=search).latest("started_at")
    assert run.status == ModelSearchRun.Status.SUCCESS


def test_run_model_search_unknown_id():
    with pytest.raises(CommandError):
        call_command("run_model_search", "999999")
