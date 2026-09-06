import pytest

from backtesting.engine import run_backtest
from backtesting.models import (
    BacktestFold,
    BacktestPrediction,
    BacktestRun,
    BacktestTrade,
)
from backtesting.tests.factories import (
    make_backtest,
    make_instrument,
    make_price_series,
    make_trading_model,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def inst():
    obj = make_instrument("ENGRO")
    make_price_series(obj, n=420)
    return obj


def test_walk_forward_runs_and_persists(inst):
    model = make_trading_model([inst], estimator_key="ridge")
    bt = make_backtest(model, train_span=120, test_span=20, step=20)

    run = run_backtest(bt)

    assert run.status == BacktestRun.Status.SUCCESS, run.error
    assert run.n_folds and run.n_folds > 1
    assert BacktestFold.objects.filter(run=run).count() == run.n_folds
    assert BacktestPrediction.objects.filter(run=run).count() == run.n_predictions > 0
    assert BacktestTrade.objects.filter(run=run).exists()
    assert run.equity_curve and len(run.equity_curve[0]) == 2

    acc = run.metrics["accuracy"]
    assert "mae" in acc and "skill_vs_naive" in acc
    trading = run.metrics["trading"]
    assert "cagr" in trading and "max_drawdown" in trading


def test_naive_baseline_is_beatable_reference(inst):
    naive = run_backtest(
        make_backtest(make_trading_model([inst], estimator_key="naive_last"), name="naive")
    )
    ridge = run_backtest(
        make_backtest(make_trading_model([inst], estimator_key="ridge"), name="ridge")
    )
    assert naive.status == ridge.status == BacktestRun.Status.SUCCESS
    # naive predicts "close unchanged" -> its skill vs the naive benchmark is ~0
    assert abs(naive.metrics["accuracy"]["skill_vs_naive"]) < 1e-6


def test_multistep_target_is_rejected_without_raising(inst):
    # Backtest.clean() blocks this at the form layer; the engine also refuses
    # rather than crash if a row is built directly.
    model = make_trading_model([inst], target={"type": "multistep", "steps": 3})
    run = run_backtest(make_backtest(model, name="ms"))
    assert run.status == BacktestRun.Status.FAILED
    assert run.error


def test_too_little_history_fails_cleanly(inst):
    model = make_trading_model([inst], estimator_key="ridge")
    bt = make_backtest(model, train_span=1000, test_span=50, step=50)
    run = run_backtest(bt)
    assert run.status == BacktestRun.Status.FAILED
    assert "fold" in run.error.lower() or "history" in run.error.lower()
