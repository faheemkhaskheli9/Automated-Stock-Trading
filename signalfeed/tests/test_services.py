from datetime import date
from unittest import mock

import pytest

from signalfeed import services
from signalfeed.models import WeeklySignal
from signalfeed.tests.factories import (
    make_instrument,
    make_price_series,
    make_watch_item,
    make_weekly_model,
)

pytestmark = pytest.mark.django_db

MON = date(2026, 2, 2)  # a Monday inside the synthetic series
FRI = date(2026, 2, 6)


@pytest.fixture
def watch():
    inst = make_instrument("ENGRO")
    make_price_series(inst, n=420)
    model = make_weekly_model([inst])
    return make_watch_item(inst, model), inst, model


def test_anchor_monday():
    assert services.anchor_monday(date(2026, 2, 2)) == MON  # Monday -> itself
    assert services.anchor_monday(date(2026, 2, 5)) == MON  # Thursday -> this Monday
    assert services.anchor_monday(date(2026, 2, 7)) == date(2026, 2, 9)  # Sat -> next Monday


def test_generate_builds_one_signal_with_direction_and_magnitude(watch):
    _, inst, model = watch
    outcomes = services.generate_weekly_signals(MON)
    assert len(outcomes) == 1
    sig = outcomes[0].signal
    assert sig.instrument == inst and sig.trading_model == model
    assert sig.as_of == MON and sig.target_date == FRI
    assert sig.direction in {
        WeeklySignal.Direction.UP,
        WeeklySignal.Direction.DOWN,
        WeeklySignal.Direction.FLAT,
    }
    assert sig.reference_close and sig.reference_close > 0
    assert sig.predicted_close and sig.predicted_close > 0
    assert sig.expected_return_pct is not None
    assert sig.model_prediction is not None
    # magnitude is internally consistent with the predicted price level
    implied = (sig.predicted_close / sig.reference_close - 1.0) * 100.0
    assert sig.expected_return_pct == pytest.approx(implied, rel=1e-6)


def test_generate_populates_sizing_hint_for_deliverable_call():
    inst = make_instrument("SIZE")
    make_price_series(inst, n=420)
    model = make_weekly_model([inst])
    make_watch_item(inst, model, sizing_capital=100_000, max_position_pct=8.0)

    sig = services.generate_weekly_signals(MON)[0].signal
    assert sig.status == WeeklySignal.Status.PENDING
    assert sig.direction in {WeeklySignal.Direction.UP, WeeklySignal.Direction.DOWN}
    # perfectly-predictable series -> holdout accuracy 1.0 -> clamped to the cap
    assert sig.suggested_fraction == pytest.approx(0.08)
    assert sig.suggested_notional == pytest.approx(8_000.0)
    assert sig.suggested_shares == int(8_000.0 // sig.reference_close)
    assert sig.sizing_basis["capital"] == 100_000.0


def test_generate_no_sizing_hint_when_capital_zero(watch):
    sig = services.generate_weekly_signals(MON)[0].signal
    assert sig.suggested_fraction is None
    assert sig.suggested_shares is None
    assert sig.sizing_basis == {}


def test_generate_no_sizing_hint_when_suppressed(watch, monkeypatch):
    item, _, _ = watch
    monkeypatch.setattr(
        "signalfeed.gate._holdout_stats",
        lambda m: {"source": "holdout", "n": 20, "directional_accuracy": 0.50, "skill": 0.0},
    )
    monkeypatch.setattr("signalfeed.gate._live_stats", lambda m, board=None: None)
    item.sizing_capital = 100_000
    item.min_directional_accuracy = 0.60
    item.save(update_fields=["sizing_capital", "min_directional_accuracy"])

    sig = services.generate_weekly_signals(MON)[0].signal
    assert sig.status == WeeklySignal.Status.SUPPRESSED
    assert sig.suggested_shares is None


def test_format_signal_includes_size_line(watch):
    item, _, _ = watch
    item.sizing_capital = 100_000
    item.save(update_fields=["sizing_capital"])
    services.generate_weekly_signals(MON)
    sig = WeeklySignal.objects.get()
    _, message = services._format_signal(sig)
    assert "Suggested size" in message


def test_generate_is_idempotent_upsert(watch):
    services.generate_weekly_signals(MON)
    services.generate_weekly_signals(MON)
    assert WeeklySignal.objects.count() == 1


def test_generate_suppresses_when_gate_fails(watch, monkeypatch):
    item, _, _ = watch
    monkeypatch.setattr(
        "signalfeed.gate._holdout_stats",
        lambda m: {"source": "holdout", "n": 20, "directional_accuracy": 0.50, "skill": 0.0},
    )
    monkeypatch.setattr("signalfeed.gate._live_stats", lambda m, board=None: None)
    item.min_directional_accuracy = 0.60
    item.save(update_fields=["min_directional_accuracy"])
    sig = services.generate_weekly_signals(MON)[0].signal
    assert sig.status == WeeklySignal.Status.SUPPRESSED
    assert sig.suppression_reason


def test_generate_flat_below_threshold(watch):
    item, _, _ = watch
    item.min_expected_move_pct = 999.0
    item.save(update_fields=["min_expected_move_pct"])
    sig = services.generate_weekly_signals(MON)[0].signal
    assert sig.direction == WeeklySignal.Direction.FLAT


def test_generate_records_error_row_when_prediction_fails(watch, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no artifact / bad data")

    monkeypatch.setattr("modeling.services.predict", boom)
    sig = services.generate_weekly_signals(MON)[0].signal
    assert sig.status == WeeklySignal.Status.ERROR
    assert "failed" in sig.suppression_reason
    assert sig.direction == WeeklySignal.Direction.FLAT


def test_send_weekly_signals_delivers_via_stub(watch, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "signalfeed.delivery.deliver",
        lambda s, m, channels=None: calls.append((s, m)) or ["telegram"],
    )
    summary = services.send_weekly_signals(MON)
    assert summary["generated"] == 1
    assert summary["sent"] == 1
    assert calls and "ENGRO" in calls[0][0]
    sig = WeeklySignal.objects.get()
    assert sig.status == WeeklySignal.Status.SENT
    assert sig.channels == ["telegram"] and sig.sent_at is not None


def test_send_weekly_signals_dry_run_does_not_deliver(watch, monkeypatch):
    monkeypatch.setattr(
        "signalfeed.delivery.deliver", lambda *a, **k: pytest.fail("should not deliver")
    )
    summary = services.send_weekly_signals(MON, dry_run=True)
    assert summary["generated"] == 1 and summary["sent"] == 0
    assert WeeklySignal.objects.get().status == WeeklySignal.Status.PENDING


def test_recap_backfills_actuals_and_grades(watch, monkeypatch):
    monkeypatch.setattr("signalfeed.delivery.deliver", lambda s, m, channels=None: ["email"])
    monkeypatch.setattr("signalfeed.services.deliver_signal", lambda sig, channels=None: ["email"])
    services.send_weekly_signals(MON)
    sig = WeeklySignal.objects.get()
    sig.status = WeeklySignal.Status.SENT
    sig.save(update_fields=["status"])

    summary = services.recap_weekly_signals(date(2026, 2, 9))
    sig.refresh_from_db()
    assert sig.actual_close and sig.actual_close > 0
    assert sig.actual_return_pct is not None
    assert sig.was_correct is not None
    assert summary["scored_now"] == 1
    assert summary["week_total"] == 1


def test_generate_builds_leaderboard_once_for_all_watch_items():
    """The accuracy leaderboard is expensive (scores every active model) -
    generate_weekly_signals must build it once per call, not once per watch
    item, even with several active items on the watchlist."""
    import modeling.leaderboard as lb_mod

    inst1 = make_instrument("ONE")
    inst2 = make_instrument("TWO")
    make_price_series(inst1, n=420)
    make_price_series(inst2, n=420)
    model1 = make_weekly_model([inst1])
    model2 = make_weekly_model([inst2])
    make_watch_item(inst1, model1)
    make_watch_item(inst2, model2)

    with mock.patch.object(lb_mod, "build_leaderboard", wraps=lb_mod.build_leaderboard) as spy:
        outcomes = services.generate_weekly_signals(MON)
    assert len(outcomes) == 2
    assert spy.call_count == 1


def test_recap_excludes_unsent_signals_from_week_totals(watch, monkeypatch):
    """A signal that was never SENT (e.g. suppressed by the gate, but still
    carrying a direction and later graded) must not be counted in the
    week's hit-rate - only delivered calls count."""
    monkeypatch.setattr("signalfeed.delivery.deliver", lambda s, m, channels=None: ["email"])
    services.generate_weekly_signals(MON)
    sig = WeeklySignal.objects.get()
    sig.status = WeeklySignal.Status.SUPPRESSED  # never delivered
    sig.save(update_fields=["status"])

    summary = services.recap_weekly_signals(date(2026, 2, 9))
    sig.refresh_from_db()
    # It still gets graded (actual_close backfilled)...
    assert sig.was_correct is not None
    # ...but must not appear in the week's SENT-only tally.
    assert summary["week_total"] == 0
    assert summary["week_hits"] == 0


def test_train_weekly_models_retrains_watchlist(watch):
    _, _, model = watch
    old = model.trained_at
    runs = services.train_weekly_models()
    assert len(runs) == 1
    assert runs[0].status == runs[0].Status.SUCCESS
    model.refresh_from_db()
    assert model.trained_at >= old
