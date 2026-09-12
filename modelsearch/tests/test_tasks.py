from unittest import mock

import pytest

from modelsearch.models import ModelSearchResult, ModelSearchRun
from modelsearch.services import start_search_run
from modelsearch.tasks import run_model_search_task
from modelsearch.tests.factories import make_instrument, make_price_series, make_search

pytestmark = pytest.mark.django_db


@pytest.fixture
def inst():
    obj = make_instrument("ENGRO")
    make_price_series(obj, n=340)
    return obj


def test_start_search_run_creates_row_immediately(inst):
    """The row must exist (and belong to this search) even before any
    fitting happens - the UI redirects straight to the detail page that
    reads it."""
    search = make_search([inst])
    run = start_search_run(search)
    assert ModelSearchRun.objects.filter(pk=run.pk, search=search).exists()


def test_start_search_run_completes_under_eager_celery(inst, settings):
    """CELERY_TASK_ALWAYS_EAGER (the pytest/dev default) means .delay() runs
    inline - by the time start_search_run returns, the run is done and its
    results are persisted, same end state as the old synchronous call."""
    settings.CELERY_TASK_ALWAYS_EAGER = True
    search = make_search([inst])
    run = start_search_run(search)
    assert run.status == ModelSearchRun.Status.SUCCESS, run.error
    assert ModelSearchResult.objects.filter(run=run).exists()


def test_start_search_run_returns_immediately_against_a_real_worker(inst):
    """With eager mode off, .delay() only enqueues - the row must come back
    ``running`` and unscored, proving the request thread isn't blocked on
    the actual fit/score work."""
    with mock.patch("modelsearch.tasks.run_model_search_task.delay") as delay:
        search = make_search([inst])
        run = start_search_run(search)
    delay.assert_called_once_with(search.pk, run.pk)
    assert run.status == ModelSearchRun.Status.RUNNING
    assert not ModelSearchResult.objects.filter(run=run).exists()


def test_task_scores_into_the_given_run_id_not_a_new_one(inst):
    search = make_search([inst])
    run = ModelSearchRun.objects.create(search=search)
    returned_pk = run_model_search_task(search.pk, run.pk)
    assert returned_pk == run.pk
    run.refresh_from_db()
    assert run.status == ModelSearchRun.Status.SUCCESS, run.error
    assert ModelSearchResult.objects.filter(run=run).exists()


def test_task_without_run_id_creates_one_like_before(inst):
    search = make_search([inst])
    before = set(search.runs.values_list("pk", flat=True))
    returned_pk = run_model_search_task(search.pk)
    assert returned_pk not in before
    run = ModelSearchRun.objects.get(pk=returned_pk)
    assert run.status == ModelSearchRun.Status.SUCCESS, run.error


def test_task_missing_search_returns_none():
    assert run_model_search_task(999999) is None


def test_task_missing_run_id_falls_back_to_creating_one(inst):
    search = make_search([inst])
    returned_pk = run_model_search_task(search.pk, 999999)
    run = ModelSearchRun.objects.get(pk=returned_pk)
    assert run.pk != 999999
    assert run.status == ModelSearchRun.Status.SUCCESS, run.error
