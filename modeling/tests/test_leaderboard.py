"""Tests for the active-model accuracy leaderboard (Phase D, D8)."""

from datetime import date, datetime, timezone

import pytest
from django.urls import reverse

from modeling.leaderboard import build_leaderboard
from modeling.models import ModelPrediction, TradingModel
from modeling.tests.factories import make_instrument, make_price_series

pytestmark = pytest.mark.django_db

SERIES_START = datetime(2026, 4, 1, tzinfo=timezone.utc)
AS_OF = date(2026, 9, 6)


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user("op", password="pw")


@pytest.fixture
def bars():
    inst = make_instrument("ENGRO")
    series = make_price_series(inst, n=170, start=SERIES_START)  # .. ~2026-09-17
    return inst, series


def _model(name, *, target=None, active=True):
    return TradingModel.objects.create(
        name=name,
        estimator_key="ridge",
        feature_spec=[{"kind": "ohlc", "fields": ["close"], "lags": [0]}],
        target_spec=target or {"type": "horizon_close", "horizon": 1},
        is_active=active,
    )


def _pred(model, inst, decision_bar, target_bar, *, predicted, actual=None):
    """One backfilled prediction: decide at ``decision_bar``, target the close
    on ``target_bar``'s date."""
    actual = target_bar.close if actual is None else actual
    return ModelPrediction.objects.create(
        model=model,
        instrument=inst,
        as_of=decision_bar.timestamp,
        target_date=target_bar.timestamp.date(),
        predicted_value=predicted,
        actual_value=actual,
        abs_error=abs(predicted - actual),
    )


def _fill(model, inst, series, *, error, direction):
    """Populate 20 in-window predictions. ``error`` sets |predicted-actual|;
    ``direction`` is +1 to call the move right, -1 to call it backwards."""
    for i in range(120, 140):  # ~2026-07-30 .. 2026-08-18, inside a 90d window
        base = series[i].close
        actual = series[i + 1].close
        move = actual - base
        if direction > 0:
            predicted = actual + error  # right direction, small error
        else:
            predicted = base - 3 * move - error  # opposite direction, large error
        _pred(model, inst, series[i], series[i + 1], predicted=predicted, actual=actual)


def test_login_required(client):
    resp = client.get(reverse("modeling:leaderboard"))
    assert resp.status_code == 302 and "login" in resp["Location"]


def test_ranks_accurate_model_first(bars):
    inst, series = bars
    good = _model("Sharp model")
    bad = _model("Blunt model")
    _fill(good, inst, series, error=0.05, direction=1)
    _fill(bad, inst, series, error=8.0, direction=-1)

    board = build_leaderboard(window_days=90, as_of=AS_OF)
    assert [r.model.name for r in board.ranked] == ["Sharp model", "Blunt model"]
    top = board.ranked[0]
    assert top.rank == 1 and top.n == 20
    assert top.mae < board.ranked[1].mae
    assert top.skill > 0 > board.ranked[1].skill
    assert top.directional_accuracy == 1.0


def test_inactive_and_unscored_models(bars):
    inst, series = bars
    active_scored = _model("Scored")
    _fill(active_scored, inst, series, error=0.1, direction=1)
    _model("No predictions yet")
    _model("Dormant", active=False)

    board = build_leaderboard(window_days=90, as_of=AS_OF)
    assert [r.model.name for r in board.ranked] == ["Scored"]
    assert [m.name for m in board.unscored] == ["No predictions yet"]


def test_predictions_outside_window_are_ignored(bars):
    inst, series = bars
    model = _model("Old only")
    # target dates in April/May 2026 - well before a 90d window ending 2026-09-06
    for i in range(5, 15):
        _pred(model, inst, series[i], series[i + 1], predicted=series[i + 1].close)

    board = build_leaderboard(window_days=90, as_of=AS_OF)
    assert not board.ranked
    assert [m.name for m in board.unscored] == ["Old only"]


def test_direction_target_scored_as_classifier(bars):
    inst, series = bars
    model = _model("Up or down", target={"type": "direction", "horizon": 1})
    for i in range(120, 140):
        base = series[i].close
        went_up = 1.0 if series[i + 1].close > base else 0.0
        ModelPrediction.objects.create(
            model=model,
            instrument=inst,
            as_of=series[i].timestamp,
            target_date=series[i + 1].timestamp.date(),
            predicted_value=went_up,  # always right
            actual_value=went_up,
            abs_error=0.0,
        )

    board = build_leaderboard(window_days=90, as_of=AS_OF)
    row = board.ranked[0]
    assert row.task == "classification"
    assert row.mae is None  # MAE is meaningless for the direction classifier
    assert row.directional_accuracy == 1.0  # every call was right
    # skill beats the majority-class baseline (or is undefined if the window
    # happened to hold a single class)
    assert row.skill is None or row.skill >= 0


def test_page_renders_with_fixture_data(client, user, bars):
    inst, series = bars
    good = _model("Sharp model")
    bad = _model("Blunt model")
    _fill(good, inst, series, error=0.05, direction=1)
    _fill(bad, inst, series, error=8.0, direction=-1)
    _model("Idle model")

    client.force_login(user)
    resp = client.get(reverse("modeling:leaderboard"))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Accuracy leaderboard" in body
    assert body.index("Sharp model") < body.index("Blunt model")
    assert "Idle model" in body  # listed as active-but-unranked


def test_window_query_param_validated(client, user, bars):
    client.force_login(user)
    resp = client.get(reverse("modeling:leaderboard"), {"window": "bogus"})
    assert resp.status_code == 200 and resp.context["window"] == 90
    resp = client.get(reverse("modeling:leaderboard"), {"window": "30"})
    assert resp.context["window"] == 30
