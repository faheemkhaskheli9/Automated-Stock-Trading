import pytest

from signalfeed.gate import evaluate_gate
from signalfeed.tests.factories import (
    make_instrument,
    make_price_series,
    make_watch_item,
    make_weekly_model,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def item():
    inst = make_instrument("ENGRO")
    make_price_series(inst, n=420)
    model = make_weekly_model([inst])
    return make_watch_item(inst, model)


def test_gate_passes_with_low_bar(item):
    result = evaluate_gate(item)
    assert result.passed, result.reason
    assert result.stats.get("source") in {"holdout", "leaderboard"}
    assert result.stats.get("directional_accuracy") is not None


def test_gate_blocks_on_high_accuracy_requirement(item, monkeypatch):
    # Pin the model's measured stats so the gate threshold is what's tested,
    # not the (perfectly predictable) synthetic training series.
    monkeypatch.setattr("signalfeed.gate._live_stats", lambda m, board=None: None)
    monkeypatch.setattr(
        "signalfeed.gate._holdout_stats",
        lambda m: {"source": "holdout", "n": 20, "directional_accuracy": 0.52, "skill": 0.01},
    )
    item.min_directional_accuracy = 0.60
    result = evaluate_gate(item)
    assert not result.passed
    assert "directional accuracy" in result.reason


def test_gate_blocks_untrained_model():
    inst = make_instrument("HBL")
    model = make_weekly_model([inst], train=False)
    item = make_watch_item(inst, model)
    result = evaluate_gate(item)
    assert not result.passed
    assert "trained" in result.reason


def test_gate_blocks_inactive_model(item):
    item.trading_model.is_active = False
    item.trading_model.save(update_fields=["is_active"])
    result = evaluate_gate(item)
    assert not result.passed
    assert "not active" in result.reason


def test_gate_skill_requirement(item, monkeypatch):
    monkeypatch.setattr("signalfeed.gate._live_stats", lambda m, board=None: None)
    monkeypatch.setattr(
        "signalfeed.gate._holdout_stats",
        lambda m: {"source": "holdout", "n": 20, "directional_accuracy": 0.8, "skill": 0.02},
    )
    item.min_skill = 0.10
    result = evaluate_gate(item)
    assert not result.passed
    assert "skill" in result.reason


def test_gate_skill_not_computable_blocks_when_required(item, monkeypatch):
    monkeypatch.setattr("signalfeed.gate._live_stats", lambda m, board=None: None)
    monkeypatch.setattr(
        "signalfeed.gate._holdout_stats",
        lambda m: {"source": "holdout", "n": 20, "directional_accuracy": 0.8, "skill": None},
    )
    item.min_skill = 0.05
    result = evaluate_gate(item)
    assert not result.passed
    assert "not computable" in result.reason


def test_gate_accepts_a_prebuilt_leaderboard(item, monkeypatch):
    """A caller evaluating several watch items in one request/task can build
    the leaderboard once and pass it in - evaluate_gate must use it instead
    of building its own."""
    calls = {"build": 0}

    def fake_build_leaderboard(window_days):
        calls["build"] += 1
        return object()

    monkeypatch.setattr("modeling.leaderboard.build_leaderboard", fake_build_leaderboard)
    monkeypatch.setattr(
        "signalfeed.gate._holdout_stats",
        lambda m: {"source": "holdout", "n": 20, "directional_accuracy": 0.8, "skill": 0.1},
    )

    class _EmptyBoard:
        ranked = []

    evaluate_gate(item, board=_EmptyBoard())
    assert calls["build"] == 0  # never rebuilt the leaderboard
