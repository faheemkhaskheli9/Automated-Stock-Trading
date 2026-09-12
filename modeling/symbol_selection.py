"""Pick which instrument to train the Monday->Friday (``weekday_anchored``)
suite on.

Not every instrument has enough paired Monday/Friday history to make a
meaningful weekly forecast - thin or newly-listed symbols can have gaps that
break a whole trading week, and illiquid names are noisy to begin with. This
ranks active instruments by how well-suited their price history is for that
target, so :mod:`modeling.weekday_suite` (and its UI / management-command
callers) can auto-pick a sane default instead of the operator guessing.

Deliberately Django-model-using (unlike ``features.py``/``targets.py``) since
this is a read-only service, not schema-adjacent validation logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db.models import Avg, F
from django.utils import timezone

from marketdata.models import Instrument, PriceBar

# Roughly 5 months of weekly Monday+Friday pairs - below this a fit is mostly
# noise, but we still surface the instrument (marked not viable) rather than
# hide it, so the operator can see *why* it was skipped.
MIN_WEEKDAY_PAIRS = 20
LIQUIDITY_LOOKBACK_DAYS = 180


def _tz() -> str:
    return getattr(settings, "TIME_ZONE", "Asia/Karachi") or "Asia/Karachi"


@dataclass
class SymbolScore:
    instrument: Instrument
    bar_count: int
    weekday_pairs: int
    coverage: float
    avg_dollar_volume: float
    last_bar_date: date | None
    viable: bool
    score: float
    reasons: list[str] = field(default_factory=list)


def _local_dates(instrument: Instrument) -> list[date]:
    tz = ZoneInfo(_tz())
    timestamps = (
        PriceBar.objects.filter(instrument=instrument, timeframe=PriceBar.Timeframe.DAILY)
        .order_by("timestamp")
        .values_list("timestamp", flat=True)
    )
    return [ts.astimezone(tz).date() for ts in timestamps]


def _weekday_pairs(dates: set[date]) -> int:
    """Count Mondays in ``dates`` whose same-week Friday is also present."""
    return sum(1 for d in dates if d.weekday() == 0 and (d + timedelta(days=4)) in dates)


def score_instruments(
    candidates: list[Instrument] | None = None,
    *,
    min_weekday_pairs: int = MIN_WEEKDAY_PAIRS,
    as_of: date | None = None,
) -> list[SymbolScore]:
    """Rank ``candidates`` (default: active instruments) for suitability.

    Returns every candidate with at least one bar, ranked viable-first then
    by descending ``score``; a low-coverage instrument is included (with
    ``viable=False`` and a ``reasons`` entry) rather than silently dropped,
    so the picker UI can explain why it wasn't auto-selected.
    """
    instruments = (
        list(candidates)
        if candidates is not None
        else list(Instrument.objects.filter(is_active=True))
    )
    as_of = as_of or timezone.localdate()
    liquidity_cutoff = as_of - timedelta(days=LIQUIDITY_LOOKBACK_DAYS)

    scored: list[SymbolScore] = []
    for instrument in instruments:
        dates = _local_dates(instrument)
        if not dates:
            continue
        date_set = set(dates)
        pairs = _weekday_pairs(date_set)
        span_days = (dates[-1] - dates[0]).days + 1
        expected_sessions = max(span_days * 5 / 7, 1)
        coverage = min(len(dates) / expected_sessions, 1.0)

        avg_dollar_volume = PriceBar.objects.filter(
            instrument=instrument,
            timeframe=PriceBar.Timeframe.DAILY,
            timestamp__date__gte=liquidity_cutoff,
        ).aggregate(v=Avg(F("close") * F("volume")))["v"]
        avg_dollar_volume = float(avg_dollar_volume) if avg_dollar_volume is not None else 0.0

        viable = pairs >= min_weekday_pairs
        reasons = (
            [] if viable else [f"only {pairs} Monday/Friday pairs (need >= {min_weekday_pairs})"]
        )

        scored.append(
            SymbolScore(
                instrument=instrument,
                bar_count=len(dates),
                weekday_pairs=pairs,
                coverage=coverage,
                avg_dollar_volume=avg_dollar_volume,
                last_bar_date=dates[-1],
                viable=viable,
                score=0.0,
                reasons=reasons,
            )
        )

    if not scored:
        return []

    max_pairs = max(s.weekday_pairs for s in scored) or 1
    max_volume = max(s.avg_dollar_volume for s in scored) or 1.0
    for s in scored:
        pairs_norm = s.weekday_pairs / max_pairs
        volume_norm = (s.avg_dollar_volume / max_volume) if max_volume else 0.0
        s.score = round(0.5 * pairs_norm + 0.3 * volume_norm + 0.2 * s.coverage, 4)

    scored.sort(key=lambda s: (not s.viable, -s.score))
    return scored


def best_symbol(candidates: list[Instrument] | None = None, **kwargs) -> Instrument | None:
    """The top viable instrument, or ``None`` if nothing clears the bar."""
    for s in score_instruments(candidates, **kwargs):
        if s.viable:
            return s.instrument
    return None
