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


def test_multistep_target_scores_on_final_step(inst):
    # A multi-output modeling model is backtestable: the engine collapses the
    # vector forecast to its last horizon and trades that.
    model = make_trading_model(
        [inst], estimator_key="ridge", target={"type": "multistep", "steps": 3}
    )
    bt = make_backtest(model, name="ms", train_span=120, test_span=20, step=20)

    run = run_backtest(bt)

    assert run.status == BacktestRun.Status.SUCCESS, run.error
    assert run.n_predictions > 0
    assert run.metrics["target"] == "multistep"
    assert run.metrics["multioutput"] is True
    # one scalar predicted/actual per row, not a vector
    p = BacktestPrediction.objects.filter(run=run).first()
    assert p.predicted_value is not None and p.actual_value is not None
    assert run.metrics["accuracy"]["n"] == run.n_predictions


def test_weekday_anchored_target_runs(inst):
    model = make_trading_model(
        [inst],
        estimator_key="ridge",
        target={"type": "weekday_anchored", "entry_weekday": 0, "exit_weekday": 4},
    )
    # decision points are weekly here, so the spans are counted in weeks
    bt = make_backtest(model, name="wa", train_span=20, test_span=4, step=4)

    run = run_backtest(bt)

    assert run.status == BacktestRun.Status.SUCCESS, run.error
    assert run.n_folds and run.n_predictions > 0
    assert run.metrics["target"] == "weekday_anchored"
    assert BacktestTrade.objects.filter(run=run).exists()


def test_multistep_and_weekday_anchored_pass_backtest_clean(inst):
    from backtesting.forms import BacktestConfigForm

    for target in (
        {"type": "multistep", "steps": 3},
        {"type": "weekday_anchored", "entry_weekday": 0, "exit_weekday": 4},
    ):
        model = make_trading_model([inst], estimator_key="ridge", target=target)
        form = BacktestConfigForm(
            data={
                "name": "x",
                "model": model.pk,
                "scheme": "expanding",
                "train_span": 20,
                "test_span": 4,
                "step": 4,
                "gap": 1,
                "long_threshold": 0.0,
                "initial_cash": 100_000.0,
                "commission_bps": 0.0,
                "slippage_bps": 0.0,
            }
        )
        assert form.is_valid(), form.errors


def test_too_little_history_fails_cleanly(inst):
    model = make_trading_model([inst], estimator_key="ridge")
    bt = make_backtest(model, train_span=1000, test_span=50, step=50)
    run = run_backtest(bt)
    assert run.status == BacktestRun.Status.FAILED
    assert "fold" in run.error.lower() or "history" in run.error.lower()
