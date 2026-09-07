"""Orchestration shared by the management commands, Celery tasks and views.

Heavy imports (``modeling`` pulls in scikit-learn) stay inside the functions
so importing ``signalfeed.services`` - and therefore ``signalfeed.tasks`` at
Celery autodiscovery - stays cheap, matching ``modeling.services``.

Flow:
    train_weekly_models()      # refit the watchlist's models (weekly-ish)
    send_weekly_signals()      # Monday: build + push this week's calls
    recap_weekly_signals()     # Friday: backfill actuals + running hit-rate
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# date helpers
# --------------------------------------------------------------------------
def anchor_monday(day: date) -> date:
    """The Monday a signal run on ``day`` is anchored to: this week's Monday
    on Mon-Fri, the upcoming Monday on the weekend."""
    wd = day.weekday()
    if wd == 0:
        return day
    if wd <= 4:
        return day - timedelta(days=wd)
    return day + timedelta(days=7 - wd)


def _local_midnight(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=ZoneInfo(settings.TIME_ZONE))


def _reference_close(instrument, moment: datetime) -> float | None:
    """Last daily close strictly known at ``moment`` (i.e. the prior session's
    close when ``moment`` is Monday midnight)."""
    from marketdata.models import PriceBar

    bar = (
        PriceBar.objects.filter(
            instrument=instrument,
            timeframe=PriceBar.Timeframe.DAILY,
            timestamp__lt=moment,
        )
        .order_by("-timestamp")
        .first()
    )
    return float(bar.close) if bar else None


def _close_on(instrument, day: date) -> float | None:
    from marketdata.models import PriceBar

    lo = _local_midnight(day)
    bar = (
        PriceBar.objects.filter(
            instrument=instrument,
            timeframe=PriceBar.Timeframe.DAILY,
            timestamp__gte=lo,
            timestamp__lt=lo + timedelta(days=1),
        )
        .order_by("timestamp")
        .first()
    )
    return float(bar.close) if bar else None


# --------------------------------------------------------------------------
# forecast -> signal translation
# --------------------------------------------------------------------------
def _interpret(ttype, pred, reference_close, flat_threshold_pct):
    """(predicted_close, expected_return_pct, direction) from a ModelPrediction."""
    from .models import WeeklySignal

    up, down, flat = (
        WeeklySignal.Direction.UP,
        WeeklySignal.Direction.DOWN,
        WeeklySignal.Direction.FLAT,
    )
    pv = pred.predicted_value

    if ttype == "direction":
        if pv is None:
            return None, None, flat
        return None, None, (up if pv >= 0.5 else down)

    if pv is None:
        return None, None, flat

    if ttype == "horizon_return":
        expected_return_pct = pv * 100.0
        predicted_close = reference_close * (1.0 + pv) if reference_close else None
    else:  # weekday_anchored / horizon_close -> a predicted price level
        predicted_close = pv
        expected_return_pct = ((pv / reference_close) - 1.0) * 100.0 if reference_close else None

    if expected_return_pct is None:
        direction = flat
    elif expected_return_pct >= flat_threshold_pct:
        direction = up
    elif expected_return_pct <= -flat_threshold_pct:
        direction = down
    else:
        direction = flat
    return predicted_close, expected_return_pct, direction


def _size_hint(item, direction, stats, reference_close):
    """Advisory position-sizing hint for a deliverable call (or ``None``)."""
    from .sizing import suggest_size

    return suggest_size(
        direction=direction,
        directional_accuracy=(stats or {}).get("directional_accuracy"),
        capital=float(item.sizing_capital or 0.0),
        max_position_pct=item.max_position_pct,
        kelly_fraction=item.kelly_fraction,
        reference_close=reference_close,
    )


def _format_signal(sig):
    arrow = {"up": "▲", "down": "▼", "flat": "▬"}.get(sig.direction, "")
    sym = sig.instrument.symbol
    subject = f"PSX weekly signal: {sym} {sig.direction.upper()} for {sig.target_date:%a %d %b}"
    lines = [
        f"{sym}  {arrow} {sig.direction.upper()}",
        f"Week: Mon {sig.as_of:%d %b} -> Fri {sig.target_date:%d %b %Y}",
    ]
    if sig.expected_return_pct is not None:
        lines.append(f"Expected move: {sig.expected_return_pct:+.2f}%")
    if sig.predicted_close is not None:
        ref = f" (from {sig.reference_close:.2f})" if sig.reference_close else ""
        lines.append(f"Predicted close: {sig.predicted_close:.2f}{ref}")
    if sig.suggested_shares:
        cap = (sig.sizing_basis or {}).get("capital")
        cap_txt = f" of {cap:,.0f}" if cap else ""
        lines.append(
            f"Suggested size: {sig.suggested_shares:,} sh "
            f"(~{sig.suggested_notional:,.0f}, {sig.suggested_fraction:.1%}{cap_txt})"
        )
    st = sig.model_stats or {}
    if st.get("directional_accuracy") is not None:
        extra = ""
        if st.get("skill") is not None:
            extra += f", skill {st['skill']:+.2f}"
        if st.get("n"):
            extra += f", n={st['n']}"
        lines.append(f"Model hit-rate: {st['directional_accuracy']:.0%}{extra}")
    lines.append(f"Model: {sig.trading_model.name if sig.trading_model else '-'}")
    lines.append("Advisory only - not an order. Weekly forecasts are uncertain.")
    return subject, "\n".join(lines)


# --------------------------------------------------------------------------
# generation
# --------------------------------------------------------------------------
@dataclass
class SignalOutcome:
    signal: object
    delivered: bool = False
    channels: list = field(default_factory=list)


def generate_weekly_signals(as_of: date | None = None) -> list[SignalOutcome]:
    """Build (and upsert) one :class:`WeeklySignal` per active watch item for
    the week ``as_of`` falls in. Does not deliver anything."""
    from modeling import services as modeling_services
    from modeling import targets as target_mod

    from .gate import evaluate_gate
    from .models import WatchItem, WeeklySignal

    as_of = as_of or timezone.localdate()
    monday = anchor_monday(as_of)
    decision_moment = _local_midnight(monday)

    outcomes: list[SignalOutcome] = []
    items = WatchItem.objects.filter(is_active=True).select_related("instrument", "trading_model")
    for item in items:
        model = item.trading_model
        try:
            ttype = target_mod.validate_spec(model.target_spec)["type"]
        except Exception:  # noqa: BLE001
            ttype = None

        derived = target_mod.derive_target_date(model.target_spec, monday)
        target_date = derived or (monday + timedelta(days=4))
        reference_close = _reference_close(item.instrument, decision_moment)
        gate = evaluate_gate(item)

        base_defaults = {
            "watch_item": item,
            "instrument": item.instrument,
            "trading_model": model,
            "as_of": monday,
            "reference_close": reference_close,
            "flat_threshold_pct": item.min_expected_move_pct,
            "model_stats": gate.stats,
            "confidence": gate.stats.get("directional_accuracy"),
            # No sizing hint unless the call below turns out deliverable.
            "suggested_fraction": None,
            "suggested_notional": None,
            "suggested_shares": None,
            "sizing_basis": {},
        }

        try:
            pred = modeling_services.predict(
                model,
                item.instrument,
                monday,
                target_date=None if derived else target_date,
            )
        except Exception as exc:  # noqa: BLE001 - isolate per watch item
            logger.exception(
                "signalfeed: prediction failed for %s / model %s",
                item.instrument.symbol,
                model.pk,
            )
            sig, _ = WeeklySignal.objects.update_or_create(
                instrument=item.instrument,
                trading_model=model,
                target_date=target_date,
                defaults={
                    **base_defaults,
                    "model_prediction": None,
                    "direction": WeeklySignal.Direction.FLAT,
                    "predicted_close": None,
                    "expected_return_pct": None,
                    "status": WeeklySignal.Status.ERROR,
                    "suppression_reason": f"prediction failed: {exc}"[:255],
                },
            )
            outcomes.append(SignalOutcome(sig))
            continue

        predicted_close, expected_return_pct, direction = _interpret(
            ttype, pred, reference_close, item.min_expected_move_pct
        )
        status = WeeklySignal.Status.PENDING if gate.passed else WeeklySignal.Status.SUPPRESSED

        size_defaults = {}
        if status == WeeklySignal.Status.PENDING:
            size = _size_hint(item, direction, gate.stats, reference_close)
            if size is not None:
                size_defaults = {
                    "suggested_fraction": size.fraction,
                    "suggested_notional": size.notional,
                    "suggested_shares": size.shares,
                    "sizing_basis": size.basis,
                }

        sig, _ = WeeklySignal.objects.update_or_create(
            instrument=item.instrument,
            trading_model=model,
            target_date=target_date,
            defaults={
                **base_defaults,
                **size_defaults,
                "model_prediction": pred,
                "direction": direction,
                "predicted_close": predicted_close,
                "expected_return_pct": expected_return_pct,
                "status": status,
                "suppression_reason": "" if gate.passed else gate.reason[:255],
            },
        )
        outcomes.append(SignalOutcome(sig))
    return outcomes


def deliver_signal(sig, *, channels=None) -> list[str]:
    from .delivery import deliver
    from .models import WeeklySignal

    subject, message = _format_signal(sig)
    sent = deliver(subject, message, channels=channels)
    if sent:
        sig.channels = sent
        sig.status = WeeklySignal.Status.SENT
        sig.sent_at = timezone.now()
        sig.save(update_fields=["channels", "status", "sent_at", "updated_at"])
    return sent


def send_weekly_signals(
    as_of: date | None = None,
    *,
    dry_run: bool = False,
    include_flat: bool = False,
    channels=None,
) -> dict:
    """Generate this week's signals and deliver the deliverable ones."""
    from .models import WeeklySignal

    outcomes = generate_weekly_signals(as_of)
    summary = {
        "generated": len(outcomes),
        "sent": 0,
        "suppressed": 0,
        "flat": 0,
        "errors": 0,
        "signals": [],
    }
    for oc in outcomes:
        sig = oc.signal
        if sig.status == WeeklySignal.Status.ERROR:
            summary["errors"] += 1
        elif sig.status == WeeklySignal.Status.SUPPRESSED:
            summary["suppressed"] += 1
        if sig.direction == WeeklySignal.Direction.FLAT:
            summary["flat"] += 1

        deliverable = sig.status == WeeklySignal.Status.PENDING and (
            include_flat or sig.direction != WeeklySignal.Direction.FLAT
        )
        if deliverable and not dry_run:
            oc.channels = deliver_signal(sig, channels=channels)
            oc.delivered = bool(oc.channels)
            if oc.delivered:
                summary["sent"] += 1
        summary["signals"].append(sig)
    return summary


# --------------------------------------------------------------------------
# recap / accuracy tracking
# --------------------------------------------------------------------------
def recap_weekly_signals(
    as_of: date | None = None,
    *,
    window_days: int = 90,
    deliver_recap: bool = True,
    channels=None,
) -> dict:
    """Backfill Friday's actual close onto past signals, grade them, and send
    a short accuracy recap for the week just closed."""
    from modeling.services import backfill_actuals

    from .delivery import deliver
    from .models import WeeklySignal

    as_of = as_of or timezone.localdate()
    try:
        backfill_actuals()
    except Exception:  # noqa: BLE001 - recap must still run
        logger.exception("recap: modeling.backfill_actuals failed")

    to_grade = WeeklySignal.objects.filter(
        actual_close__isnull=True, target_date__lt=as_of
    ).select_related("instrument")
    scored_now = 0
    for sig in to_grade:
        close = _close_on(sig.instrument, sig.target_date)
        if close is None:
            continue
        sig.actual_close = close
        if sig.reference_close:
            sig.actual_return_pct = ((close / sig.reference_close) - 1.0) * 100.0
        if (
            sig.direction in (WeeklySignal.Direction.UP, WeeklySignal.Direction.DOWN)
            and sig.actual_return_pct is not None
        ):
            actual_up = sig.actual_return_pct > 0
            sig.was_correct = (sig.direction == WeeklySignal.Direction.UP) == actual_up
        sig.save(update_fields=["actual_close", "actual_return_pct", "was_correct", "updated_at"])
        scored_now += 1

    cutoff = as_of - timedelta(days=window_days)
    window_qs = WeeklySignal.objects.filter(
        was_correct__isnull=False,
        status=WeeklySignal.Status.SENT,
        target_date__gte=cutoff,
        target_date__lt=as_of,
    )
    window_total = window_qs.count()
    window_hits = window_qs.filter(was_correct=True).count()

    week_qs = WeeklySignal.objects.filter(
        was_correct__isnull=False,
        target_date__gte=as_of - timedelta(days=7),
        target_date__lt=as_of,
    ).select_related("instrument")
    week_total = week_qs.count()
    week_hits = week_qs.filter(was_correct=True).count()

    summary = {
        "as_of": as_of,
        "scored_now": scored_now,
        "window_days": window_days,
        "window_total": window_total,
        "window_hits": window_hits,
        "window_hit_rate": (window_hits / window_total) if window_total else None,
        "week_total": week_total,
        "week_hits": week_hits,
        "delivered_to": [],
    }

    if deliver_recap and week_total:
        lines = [
            f"PSX weekly signals recap - {as_of:%d %b %Y}",
            f"This week: {week_hits}/{week_total} correct ({week_hits / week_total:.0%})",
        ]
        if window_total:
            lines.append(
                f"Trailing {window_days}d: {window_hits}/{window_total} "
                f"correct ({window_hits / window_total:.0%})"
            )
        for sig in week_qs:
            mark = "OK  " if sig.was_correct else "MISS"
            if sig.expected_return_pct is not None and sig.actual_return_pct is not None:
                lines.append(
                    f"  {mark} {sig.instrument.symbol} {sig.direction.upper()} "
                    f"pred {sig.expected_return_pct:+.1f}% / actual {sig.actual_return_pct:+.1f}%"
                )
            else:
                lines.append(f"  {mark} {sig.instrument.symbol} {sig.direction.upper()}")
        summary["delivered_to"] = deliver(
            "PSX weekly signals recap", "\n".join(lines), channels=channels
        )
    return summary


# --------------------------------------------------------------------------
# training
# --------------------------------------------------------------------------
def train_weekly_models(*, model_id: int | None = None) -> list:
    """Retrain every distinct model referenced by an active watch item."""
    from modeling.models import TradingModel
    from modeling.services import train_model

    from .models import WatchItem

    ids = list(
        WatchItem.objects.filter(is_active=True)
        .values_list("trading_model_id", flat=True)
        .distinct()
    )
    if model_id is not None:
        ids = [i for i in ids if i == model_id]

    runs = []
    for mid in ids:
        model = TradingModel.objects.filter(pk=mid).first()
        if model is None:
            continue
        try:
            runs.append(train_model(model))
        except Exception:  # noqa: BLE001 - train_model records failures, but isolate anyway
            logger.exception("train_weekly_models: model %s failed", mid)
    return runs
