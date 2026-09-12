from datetime import datetime, timedelta, timezone

import pytest

from marketdata.models import PriceBar
from modeling import symbol_selection
from modeling.tests.factories import make_instrument, make_price_series

pytestmark = pytest.mark.django_db


def test_no_bars_is_excluded():
    make_instrument("EMPTY")
    scores = symbol_selection.score_instruments()
    assert scores == []


def test_well_covered_symbol_is_viable_and_ranks_first():
    thin = make_instrument("THIN")
    make_price_series(thin, n=15)  # ~2 weeks - not enough Mon/Fri pairs

    rich = make_instrument("RICH")
    make_price_series(rich, n=400)  # well over a year of daily bars

    scores = {s.instrument.symbol: s for s in symbol_selection.score_instruments()}
    assert scores["THIN"].viable is False
    assert scores["THIN"].reasons  # explains why it was skipped
    assert scores["RICH"].viable is True

    ranked = symbol_selection.score_instruments()
    assert ranked[0].instrument.symbol == "RICH"


def test_best_symbol_returns_none_when_nothing_viable():
    thin = make_instrument("THIN")
    make_price_series(thin, n=10)
    assert symbol_selection.best_symbol() is None


def test_best_symbol_picks_the_top_viable_instrument():
    rich = make_instrument("RICH")
    make_price_series(rich, n=400)
    assert symbol_selection.best_symbol() == rich


def test_higher_liquidity_breaks_a_tie_between_equally_covered_symbols():
    # Anchored so the whole series falls inside the 180-day liquidity
    # lookback window (measured from "today").
    recent_start = datetime.now(timezone.utc) - timedelta(days=200)
    a = make_instrument("AAA")
    b = make_instrument("BBB")
    make_price_series(a, n=200, start=recent_start, base=100.0)
    make_price_series(b, n=200, start=recent_start, base=100.0)
    # Give BBB much higher recent volume so it should outrank AAA despite
    # identical date coverage.
    PriceBar.objects.filter(instrument=b).update(volume=10_000_000)

    ranked = symbol_selection.score_instruments()
    ranked_by_symbol = {s.instrument.symbol: s for s in ranked}
    assert ranked_by_symbol["BBB"].avg_dollar_volume > ranked_by_symbol["AAA"].avg_dollar_volume
    assert ranked[0].instrument.symbol == "BBB"


def test_candidates_can_be_restricted():
    a = make_instrument("AAA")
    make_price_series(a, n=300)
    b = make_instrument("BBB")
    make_price_series(b, n=300)

    scores = symbol_selection.score_instruments(candidates=[a])
    assert [s.instrument.symbol for s in scores] == ["AAA"]
