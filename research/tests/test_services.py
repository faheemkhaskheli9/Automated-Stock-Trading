from datetime import datetime, timedelta, timezone

import pytest

from research.models import ResearchSnapshot
from research.services import get_or_build_snapshot

from .factories import make_instrument, make_price_series

pytestmark = pytest.mark.django_db

UTC = timezone.utc


def test_get_or_build_snapshot_caches():
    inst = make_instrument("MARI")
    make_price_series(inst, [100.0 + i for i in range(60)])
    as_of = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=59)

    first = get_or_build_snapshot("MARI", as_of)
    assert ResearchSnapshot.objects.count() == 1
    assert first.features
    assert "technical" in first.provider_keys

    second = get_or_build_snapshot("MARI", as_of)
    assert second.pk == first.pk
    assert ResearchSnapshot.objects.count() == 1


def test_rebuild_updates_in_place():
    inst = make_instrument("OGDC")
    make_price_series(inst, [100.0 + i for i in range(60)])
    as_of = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=59)

    first = get_or_build_snapshot("OGDC", as_of)
    rebuilt = get_or_build_snapshot("OGDC", as_of, rebuild=True)
    assert rebuilt.pk == first.pk
    assert ResearchSnapshot.objects.count() == 1
