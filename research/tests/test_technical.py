import pandas as pd
import pytest

from research.providers.technical import technical_features


def _frame(closes):
    idx = pd.date_range("2026-01-01", periods=len(closes), freq="D")
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes],
            "close": closes,
            "volume": [1000 + i for i in range(len(closes))],
        },
        index=idx,
    )


def test_sma_matches_manual_mean():
    closes = [float(x) for x in range(1, 61)]  # 1..60
    feats = technical_features(_frame(closes))
    assert feats["technical.sma_10"] == pytest.approx(sum(closes[-10:]) / 10)
    assert feats["technical.sma_20"] == pytest.approx(sum(closes[-20:]) / 20)
    assert feats["technical.sma_50"] == pytest.approx(sum(closes[-50:]) / 50)


def test_rsi_bounds_and_all_gains_is_100():
    closes = [float(x) for x in range(1, 40)]  # strictly increasing
    feats = technical_features(_frame(closes))
    assert feats["technical.rsi_14"] == pytest.approx(100.0)


def test_return_1d_matches_pct_change():
    closes = [100.0, 101.0, 103.0, 102.0]
    feats = technical_features(_frame(closes))
    assert feats["technical.return_1d"] == pytest.approx(102.0 / 103.0 - 1)


def test_keys_are_namespaced():
    feats = technical_features(_frame([float(x) for x in range(1, 61)]))
    assert feats
    assert all(k.startswith("technical.") for k in feats)


def test_short_history_returns_subset_not_nan():
    feats = technical_features(_frame([100.0, 101.0, 102.0]))
    # No 10/20/50-window indicator should be present yet...
    assert "technical.sma_10" not in feats
    # ...but a 1-day return should be, and nothing should be NaN.
    assert "technical.return_1d" in feats
    assert not any(v != v for v in feats.values())  # NaN != NaN


def test_empty_frame():
    assert technical_features(_frame([])) == {}
