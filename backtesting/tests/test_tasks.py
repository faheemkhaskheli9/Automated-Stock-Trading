from unittest import mock

import pytest

from backtesting.models import BacktestRun
from backtesting.services import start_backtest_run
from backtesting.tasks import run_backtest_task
from backtesting.tests.factories import (
    make_backtest,
    make_instrument,
    make_price_series,
    make_trading_model,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def backtest():
    inst = make_instrument("ENGRO")
    make_price_series(inst, n=340)
    model = make_trading_model([inst])
    return make_backtest(model)


def test_start_backtest_run_creates_row_immediately(backtest):
    """The row must exist (and belong to this backtest) even before any
    fitting happens - the UI redirects straight to the detail page that
    reads it."""
    run = start_backtest_run(backtest)
    assert BacktestRun.objects.filter(pk=run.pk, backtest=backtest).exists()


def test_start_backtest_run_completes_under_eager_celery(backtest, settings):
    """CELERY_TASK_ALWAYS_EAGER (the pytest/dev default) means .delay() runs
    inline - by the time start_backtest_run returns, the run is done and its
    results are persisted, same end state as the old synchronous call."""
    settings.CELERY_TASK_ALWAYS_EAGER = True
    run = start_backtest_run(backtest)
    assert run.status == BacktestRun.Status.SUCCESS, run.error
    assert run.folds.exists()


def test_start_backtest_run_returns_immediately_against_a_real_worker(backtest):
    """With eager mode off, .delay() only enqueues - the row must come back
    ``running`` and unscored, proving the request thread isn't blocked on
    the actual walk-forward work."""
    with mock.patch("backtesting.tasks.run_backtest_task.delay") as delay:
        run = start_backtest_run(backtest)
    delay.assert_called_once_with(backtest.pk, run.pk)
    assert run.status == BacktestRun.Status.RUNNING
    assert not run.folds.exists()


def test_task_scores_into_the_given_run_id_not_a_new_one(backtest):
    run = BacktestRun.objects.create(backtest=backtest)
    returned_pk = run_backtest_task(backtest.pk, run.pk)
    assert returned_pk == run.pk
    run.refresh_from_db()
    assert run.status == BacktestRun.Status.SUCCESS, run.error
    assert run.folds.exists()


def test_task_without_run_id_creates_one_like_before(backtest):
    before = set(backtest.runs.values_list("pk", flat=True))
    returned_pk = run_backtest_task(backtest.pk)
    assert returned_pk not in before
    run = BacktestRun.objects.get(pk=returned_pk)
    assert run.status == BacktestRun.Status.SUCCESS, run.error


def test_task_missing_backtest_returns_none():
    assert run_backtest_task(999999) is None


def test_task_missing_run_id_falls_back_to_creating_one(backtest):
    returned_pk = run_backtest_task(backtest.pk, 999999)
    run = BacktestRun.objects.get(pk=returned_pk)
    assert run.pk != 999999
    assert run.status == BacktestRun.Status.SUCCESS, run.error
