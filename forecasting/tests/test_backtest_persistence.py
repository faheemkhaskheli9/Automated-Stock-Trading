"""Persistence for the strict-path walk-forward backtester.

Covers ``forecasting.models.ForecastBacktestRun`` validation, the never-raises
``forecasting.services.run_forecast_backtest`` writer and the
``backtest_predictor --save`` path.
"""

from datetime import date, datetime
from io import StringIO
from zoneinfo import ZoneInfo

import numpy as np
import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command

from forecasting.base import BasePredictor, PricePrediction
from forecasting.models import ForecastBacktestRun
from forecasting.registry import _REGISTRY, register_predictor
from forecasting.services import run_forecast_backtest
from marketdata.models import PriceBar
from research.tests.factories import make_instrument, make_price_series

ZONE = ZoneInfo("Asia/Karachi")


def local(day, month=1):
    return datetime(2026, month, day, tzinfo=ZONE)


CFG = dict(
    provider_keys=[],
    scheme=ForecastBacktestRun.Scheme.EXPANDING,
    train_span=15,
    test_span=5,
    step=5,
    gap=1,
)


@pytest.fixture
def history(db):
    inst = make_instrument("ENGRO")
    rng = np.random.default_rng(7)
    closes = np.abs(100.0 + np.cumsum(rng.normal(0.1, 0.8, 44))) + 40.0
    make_price_series(inst, list(closes))
    return inst


# --------------------------------------------------------------------------- #
# writer - success
# --------------------------------------------------------------------------- #
def test_run_is_persisted_with_serialised_results(history):
    run = run_forecast_backtest(
        predictor_key="naive",
        symbol="ENGRO",
        start=local(1),
        end=local(20, month=2),
        name="naive smoke",
        **CFG,
    )

    assert run.pk is not None
    assert run.status == ForecastBacktestRun.Status.SUCCESS
    assert run.finished_at is not None
    assert run.error == ""
    assert run.n_folds == 5
    assert run.n_skipped_folds == 0
    assert run.n_predictions == 25
    assert run.metrics["n"] == 25
    assert run.skill_vs_naive == pytest.approx(0.0, abs=1e-9)
    assert run.looks_leaky is False
    assert len(run.equity_curve) == 25
    assert run.trading["n"] == 25

    # folds are JSON-safe: dates serialised to ISO strings
    assert len(run.folds) == 5
    first = run.folds[0]
    assert isinstance(first["train_start"], str)
    date.fromisoformat(first["train_start"])
    assert first["n_test"] == 5
    assert set(run.predictions[0]) == {
        "fold",
        "as_of",
        "target_date",
        "anchor",
        "predicted",
        "actual",
    }

    # survives a DB round-trip unchanged
    reloaded = ForecastBacktestRun.objects.get(pk=run.pk)
    assert reloaded.folds == run.folds
    assert reloaded.metrics == run.metrics


def test_config_is_frozen_on_the_row(history):
    run = run_forecast_backtest(
        predictor_key="drift",
        symbol="ENGRO",
        start=local(1),
        end=local(20, month=2),
        params={},
        cost_bps=5.0,
        **CFG,
    )
    assert run.predictor_key == "drift"
    assert run.symbol == "ENGRO"
    assert run.train_span == 15
    assert run.cost_bps == 5.0
    assert run.start == date(2026, 1, 1)
    assert run.end == date(2026, 2, 20)


# --------------------------------------------------------------------------- #
# writer - failure is recorded, never raised
# --------------------------------------------------------------------------- #
def test_history_too_short_is_recorded_as_failed(history):
    run = run_forecast_backtest(
        predictor_key="naive",
        symbol="ENGRO",
        start=local(1),
        end=local(20, month=2),
        provider_keys=[],
        train_span=200,
        test_span=5,
        step=5,
        gap=1,
    )
    assert run.status == ForecastBacktestRun.Status.FAILED
    assert "history too short" in run.error
    assert run.finished_at is not None
    assert run.n_folds is None


def test_unknown_predictor_key_is_recorded_as_failed(history):
    run = run_forecast_backtest(
        predictor_key="does-not-exist",
        symbol="ENGRO",
        start=local(1),
        end=local(20, month=2),
        **CFG,
    )
    assert run.status == ForecastBacktestRun.Status.FAILED
    assert "does-not-exist" in run.error


# --------------------------------------------------------------------------- #
# leak canary flows through to the row
# --------------------------------------------------------------------------- #
@pytest.fixture
def leaky_key():
    key = "leaky_persist_test"

    @register_predictor(key)
    class _Leaky(BasePredictor):
        display_name = "reads tomorrow's close from the DB"

        def fit(self, history):
            pass

        def predict_series(self, frame):
            future = {
                bar.timestamp.astimezone(ZONE).date(): float(bar.close)
                for bar in PriceBar.objects.filter(
                    instrument__symbol=frame.symbol,
                    instrument__exchange=frame.exchange,
                    timeframe=PriceBar.Timeframe.DAILY,
                )
            }
            out = []
            for as_of, row in frame.X.iterrows():
                target = frame.target_dates.loc[as_of]
                out.append(
                    PricePrediction(
                        target_date=target,
                        predicted_close=future.get(target, float(row["price.close"])),
                        model_key=key,
                        features_hash=frame.features_hashes.loc[as_of],
                    )
                )
            return out

    try:
        yield key
    finally:
        _REGISTRY.pop(key, None)


def test_leaky_predictor_sets_the_flag_on_the_run(history, leaky_key):
    run = run_forecast_backtest(
        predictor_key=leaky_key,
        symbol="ENGRO",
        start=local(1),
        end=local(20, month=2),
        **CFG,
    )
    assert run.status == ForecastBacktestRun.Status.SUCCESS
    assert run.looks_leaky is True


# --------------------------------------------------------------------------- #
# model validation
# --------------------------------------------------------------------------- #
def test_clean_rejects_an_unknown_predictor_key(db):
    run = ForecastBacktestRun(
        predictor_key="nope", symbol="ENGRO", start=date(2026, 1, 1), end=date(2026, 2, 1)
    )
    with pytest.raises(ValidationError) as exc:
        run.full_clean()
    assert "predictor_key" in exc.value.message_dict


def test_clean_rejects_bad_windows_and_dates(db):
    run = ForecastBacktestRun(
        predictor_key="naive",
        symbol="ENGRO",
        start=date(2026, 2, 1),
        end=date(2026, 1, 1),
        train_span=0,
        cost_bps=-1.0,
    )
    with pytest.raises(ValidationError) as exc:
        run.full_clean()
    errors = exc.value.message_dict
    assert {"train_span", "end", "cost_bps"} <= set(errors)


def test_clean_accepts_a_valid_config(db):
    run = ForecastBacktestRun(
        predictor_key="naive", symbol="ENGRO", start=date(2026, 1, 1), end=date(2026, 2, 1)
    )
    run.full_clean()  # must not raise


# --------------------------------------------------------------------------- #
# management command --save
# --------------------------------------------------------------------------- #
def test_backtest_predictor_save_flag_persists_a_run(history):
    out = StringIO()
    call_command(
        "backtest_predictor",
        "ENGRO",
        "naive",
        "--start=2026-01-01",
        "--end=2026-02-20",
        "--providers=none",
        "--train-span=15",
        "--test-span=5",
        "--step=5",
        "--gap=1",
        "--save",
        "--name=cli run",
        stdout=out,
    )
    run = ForecastBacktestRun.objects.get()
    assert run.name == "cli run"
    assert run.status == ForecastBacktestRun.Status.SUCCESS
    assert f"#{run.pk}" in out.getvalue()
