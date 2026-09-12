from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from django.urls import reverse

from research.models import CompanyFundamental, NewsItem, ResearchSnapshot
from research.views import _as_of_datetime

from .factories import make_instrument

pytestmark = pytest.mark.django_db
UTC = timezone.utc


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user("op", password="pw")


def _news(symbol="ENGRO", **kw):
    defaults = dict(
        symbol=symbol,
        exchange="PSX",
        headline=f"{symbol} posts record profit",
        url=f"https://example.com/{symbol}",
        url_hash=symbol.lower(),
        published_at=datetime(2026, 2, 1, tzinfo=UTC),
        sentiment=0.4,
    )
    defaults.update(kw)
    return NewsItem.objects.create(**defaults)


# --- _as_of_datetime -------------------------------------------------
def test_as_of_datetime_uses_project_local_midnight():
    """Must match the Asia/Karachi 'next local midnight' point-in-time
    convention used by the automated research/forecasting pipeline, not
    UTC midnight - otherwise a manual snapshot's cutoff disagrees with the
    scheduled one for the same as_of date."""
    result = _as_of_datetime(date(2026, 2, 2))
    assert result == datetime(2026, 2, 2, 0, 0, tzinfo=ZoneInfo("Asia/Karachi"))
    # Asia/Karachi is UTC+5, so local midnight is 19:00 UTC the day before -
    # not UTC midnight, which is what the old (buggy) implementation used.
    assert result.astimezone(UTC) == datetime(2026, 2, 1, 19, 0, tzinfo=UTC)


def test_as_of_datetime_none_uses_now():
    before = datetime.now(UTC)
    result = _as_of_datetime(None)
    assert result >= before


# --- index -----------------------------------------------------------
def test_index_requires_login(client):
    resp = client.get(reverse("research:index"))
    assert resp.status_code == 302 and "login" in resp["Location"]


def test_index_renders(client, user):
    _news()
    ResearchSnapshot.objects.create(
        symbol="ENGRO",
        exchange="PSX",
        as_of=datetime(2026, 2, 2, tzinfo=UTC),
        features={"technical.rsi_14": 55.0},
        provider_keys=["technical"],
    )
    client.force_login(user)
    resp = client.get(reverse("research:index"))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "ENGRO" in body
    assert "record profit" in body


# --- symbol detail --------------------------------------------------
def test_symbol_detail_renders_for_known_symbol(client, user):
    make_instrument("ENGRO")
    _news()
    client.force_login(user)
    resp = client.get(reverse("research:symbol_detail"), {"symbol": "engro"})
    assert resp.status_code == 200
    assert b"record profit" in resp.content


def test_symbol_detail_unknown_symbol_redirects(client, user):
    client.force_login(user)
    resp = client.get(reverse("research:symbol_detail"), {"symbol": "NOPE"})
    assert resp.status_code == 302
    assert resp.url == reverse("research:index")


# --- sync ----------------------------------------------------------
def test_sync_builds_snapshot(client, user, monkeypatch):
    seen = {}

    def fake_build(symbol, as_of, *, exchange="PSX", rebuild=False):
        seen.update(symbol=symbol, exchange=exchange, rebuild=rebuild)

        class S:
            features = {"a": 1.0}

        return S()

    monkeypatch.setattr("research.views.get_or_build_snapshot", fake_build)
    client.force_login(user)
    resp = client.post(
        reverse("research:sync"),
        {"symbol": "engro", "exchange": "psx", "as_of": "", "ingest_news": ""},
    )
    assert resp.status_code == 302
    assert "symbol=ENGRO" in resp.url
    assert seen == {"symbol": "ENGRO", "exchange": "PSX", "rebuild": True}


def test_sync_with_news_calls_ingest(client, user, monkeypatch):
    calls = {"ingest": 0}
    monkeypatch.setattr(
        "research.views.get_or_build_snapshot",
        lambda *a, **k: type("S", (), {"features": {}})(),
    )
    monkeypatch.setattr(
        "research.views.ingest_feeds", lambda **k: calls.__setitem__("ingest", 3) or 3
    )
    client.force_login(user)
    resp = client.post(
        reverse("research:sync"),
        {"symbol": "MARI", "exchange": "PSX", "ingest_news": "on"},
    )
    assert resp.status_code == 302
    assert calls["ingest"] == 3


def test_sync_failure_is_surfaced(client, user, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no data")

    monkeypatch.setattr("research.views.get_or_build_snapshot", boom)
    client.force_login(user)
    resp = client.post(reverse("research:sync"), {"symbol": "X", "exchange": "PSX"}, follow=True)
    assert resp.status_code == 200
    assert b"no data" in resp.content


# --- fundamentals -------------------------------------------------
def test_create_fundamental(client, user):
    client.force_login(user)
    resp = client.post(
        reverse("research:fundamental_create"),
        {
            "symbol": "engro",
            "exchange": "PSX",
            "as_of_report_date": "2026-01-31",
            "ratios": '{"pe": 8.1}',
            "source": "manual",
        },
    )
    assert resp.status_code == 302
    f = CompanyFundamental.objects.get(symbol="ENGRO")
    assert f.ratios == {"pe": 8.1}


def test_create_fundamental_bad_json(client, user):
    client.force_login(user)
    resp = client.post(
        reverse("research:fundamental_create"),
        {
            "symbol": "ENGRO",
            "exchange": "PSX",
            "as_of_report_date": "2026-01-31",
            "ratios": "not json",
        },
    )
    assert resp.status_code == 200
    assert not CompanyFundamental.objects.exists()


def test_edit_fundamental(client, user):
    f = CompanyFundamental.objects.create(
        symbol="ENGRO", exchange="PSX", as_of_report_date="2026-01-31", ratios={"pe": 8.1}
    )
    client.force_login(user)
    resp = client.post(
        reverse("research:fundamental_edit", args=[f.pk]),
        {
            "symbol": "ENGRO",
            "exchange": "PSX",
            "as_of_report_date": "2026-01-31",
            "ratios": '{"pe": 9.0}',
            "source": "",
        },
    )
    assert resp.status_code == 302
    f.refresh_from_db()
    assert f.ratios == {"pe": 9.0}
