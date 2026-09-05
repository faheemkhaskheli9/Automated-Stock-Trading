"""The load-bearing tests for this app: proving providers never see the
future. If these pass, the walk-forward backtester in Phase C can be
trusted."""

from datetime import datetime, timedelta, timezone

import pytest

from research.models import NewsItem
from research.providers.news import news_features
from research.providers.technical import TechnicalProvider, load_ohlcv, technical_features
from research.services import build_feature_bundle

from .factories import make_instrument, make_price_series

pytestmark = pytest.mark.django_db

UTC = timezone.utc


def test_technical_provider_ignores_bars_after_as_of():
    inst = make_instrument("ENGRO")
    # 40 rising days, then 20 days that crash the price.
    make_price_series(inst, [100.0 + i for i in range(40)] + [50.0] * 20)

    as_of = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=39)  # last rising day
    df = load_ohlcv("ENGRO", as_of)
    assert len(df) == 40  # the 20 crash bars are excluded
    assert df["close"].max() == pytest.approx(139.0)

    feats_pit = technical_features(df)
    feats_full = technical_features(load_ohlcv("ENGRO", as_of + timedelta(days=100)))
    # The crash must not leak backwards into the as_of snapshot.
    assert feats_pit["technical.sma_10"] != feats_full["technical.sma_10"]
    assert feats_pit["technical.sma_10"] == pytest.approx(sum(range(130, 140)) / 10)


def test_news_features_exclude_future_headlines():
    make_instrument("LUCK")
    as_of = datetime(2026, 6, 1, tzinfo=UTC)

    NewsItem.objects.create(
        symbol="LUCK",
        exchange="PSX",
        headline="past good news",
        url="http://x/1",
        url_hash="h1",
        published_at=as_of - timedelta(days=2),
        sentiment=0.8,
    )
    NewsItem.objects.create(
        symbol="LUCK",
        exchange="PSX",
        headline="FUTURE news - must not count",
        url="http://x/2",
        url_hash="h2",
        published_at=as_of + timedelta(days=1),
        sentiment=-0.9,
    )

    feats = news_features("LUCK", as_of)
    assert feats["news.count_7d"] == 1.0
    assert feats["news.sentiment_mean_7d"] == pytest.approx(0.8)  # future -0.9 excluded


def test_build_bundle_merges_namespaces_without_collision():
    inst = make_instrument("PSO")
    make_price_series(inst, [100.0 + i * 0.5 for i in range(60)])
    as_of = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=59)

    bundle = build_feature_bundle("PSO", as_of)
    namespaces = {k.split(".")[0] for k in bundle.features}
    assert "technical" in namespaces
    assert len(bundle.features) == len(set(bundle.features))  # no dup keys
    assert bundle.sources  # citations recorded


def test_provider_returns_bundle_not_raise_for_unknown_symbol():
    bundle = TechnicalProvider().get_features("NOPE", datetime(2026, 1, 1, tzinfo=UTC))
    assert bundle.features == {}
