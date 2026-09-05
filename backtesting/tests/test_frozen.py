"""Frozen-artifact fit mode: score a model the ``modeling`` app already
trained, instead of retraining a fresh pipeline every fold.

The out-of-sample guarantee here is the artifact's ``trained_at`` date - only
sessions strictly after it are scored, because the artifact never trained on
a label observable that late.
"""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings as dj_settings

from backtesting.engine import run_backtest
from backtesting.models import BacktestFold, BacktestPrediction, BacktestRun
from backtesting.tests.factories import make_backtest, make_instrument, make_trading_model
from modeling.models import ModelTrainingRun
from modeling.tests.factories import make_price_series
from modeling.training import train_model

pytestmark = pytest.mark.django_db


@pytest.fixture
def artifacts_dir(settings, tmp_path):
    settings.MODEL_ARTIFACT_DIR = tmp_path
    return tmp_path


@pytest.fixture
def inst():
    """History straddling 'now' so there are sessions after the artifact's
    (wall-clock) trained_at date to score."""
    obj = make_instrument("ENGRO")
    make_price_series(obj, n=460, start=datetime.now(timezone.utc) - timedelta(days=250))
    return obj


@pytest.fixture
def trained_model(inst, artifacts_dir):
    model = make_trading_model([inst], estimator_key="ridge")
    run = train_model(model)
    assert run.status == ModelTrainingRun.Status.SUCCESS, run.error
    model.refresh_from_db()
    return model


def test_frozen_run_scores_one_pseudo_fold(trained_model):
    bt = make_backtest(trained_model, fit_mode="frozen_artifact")

    run = run_backtest(bt)

    assert run.status == BacktestRun.Status.SUCCESS, run.error
    assert run.n_folds == 1
    folds = list(BacktestFold.objects.filter(run=run))
    assert len(folds) == 1
    assert folds[0].fold_index == 0
    assert folds[0].n_train == 0  # not retrained here
    assert run.metrics["fit_mode"] == "frozen_artifact"
    assert run.n_predictions > 0
    assert run.equity_curve


def test_frozen_only_scores_sessions_after_trained_at(trained_model):
    bt = make_backtest(trained_model, fit_mode="frozen_artifact")
    run = run_backtest(bt)
    assert run.status == BacktestRun.Status.SUCCESS, run.error

    fold = BacktestFold.objects.get(run=run)
    trained_date = fold.train_end
    tz = ZoneInfo(dj_settings.TIME_ZONE)
    earliest = min(
        p.as_of.astimezone(tz).date() for p in BacktestPrediction.objects.filter(run=run)
    )
    assert earliest > trained_date
    assert fold.test_start > trained_date


def test_frozen_without_artifact_fails_cleanly(inst, artifacts_dir):
    model = make_trading_model([inst], estimator_key="ridge")  # never trained
    bt = make_backtest(model, fit_mode="frozen_artifact")

    run = run_backtest(bt)

    assert run.status == BacktestRun.Status.FAILED
    assert "trained" in run.error.lower()


def test_frozen_pins_a_specific_training_run(trained_model):
    first = trained_model.runs.filter(status=ModelTrainingRun.Status.SUCCESS).first()
    second = train_model(trained_model)
    assert second.status == ModelTrainingRun.Status.SUCCESS, second.error

    bt = make_backtest(trained_model, fit_mode="frozen_artifact", training_run=first)
    run = run_backtest(bt)

    assert run.status == BacktestRun.Status.SUCCESS, run.error
    assert run.n_predictions > 0


def test_walk_forward_is_still_the_default(trained_model):
    bt = make_backtest(trained_model, train_span=120, test_span=20, step=20)
    assert bt.fit_mode == "walk_forward"

    run = run_backtest(bt)

    assert run.status == BacktestRun.Status.SUCCESS, run.error
    assert run.n_folds and run.n_folds > 1
    assert run.metrics["fit_mode"] == "walk_forward"
