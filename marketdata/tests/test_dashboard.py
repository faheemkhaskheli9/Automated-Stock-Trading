from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from marketdata.models import Instrument, PriceBar
from marketdata.services import sync_instrument_history

from .factories import FakeProvider


class DashboardTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser("viewer", password="test-pass")
        self.client.force_login(self.user)
        self.instrument = Instrument.objects.create(symbol="OGDC")
        sync_instrument_history(self.instrument, provider=FakeProvider())

    def test_login_required(self):
        self.client.logout()
        response = self.client.get("/")
        self.assertRedirects(response, "/login/?next=/")

    def test_saved_dashboard_does_not_fetch(self):
        with patch("marketdata.services.get_default_provider") as provider:
            response = self.client.get("/", {"symbol": "ogdc"})
        self.assertContains(response, "OGDC")
        self.assertContains(response, "Closing price")
        self.assertEqual(response.context["page"].paginator.count, 2)
        provider.assert_not_called()

    def test_csv_and_date_filter(self):
        day = PriceBar.objects.order_by("timestamp").first().timestamp.date().isoformat()
        response = self.client.get(
            "/", {"symbol": "OGDC", "start": day, "end": day, "export": "csv"}
        )
        self.assertEqual(response["Content-Type"], "text/csv")
        self.assertEqual(len(response.content.decode().splitlines()), 2)

    def test_invalid_dates(self):
        response = self.client.get(
            "/", {"symbol": "OGDC", "start": "2025-02-02", "end": "2025-01-01"}
        )
        self.assertContains(response, "Start date must be before")

    def test_sync_persists_and_upserts(self):
        with patch("marketdata.services.get_default_provider", return_value=FakeProvider()):
            for _ in range(2):
                response = self.client.post(reverse("marketdata:sync"), {"symbol": "hbl"})
                self.assertRedirects(response, "/?symbol=HBL")
        self.assertEqual(PriceBar.objects.filter(instrument__symbol="HBL").count(), 2)

    def test_failure_preserves_history(self):
        with patch("marketdata.views.sync_instrument_history", side_effect=RuntimeError("offline")):
            response = self.client.post(reverse("marketdata:sync"), {"symbol": "OGDC"}, follow=True)
        self.assertContains(response, "Could not fetch PSX data")
        self.assertEqual(PriceBar.objects.count(), 2)

    def test_empty_provider_reported(self):
        with patch("marketdata.services.get_default_provider", return_value=FakeProvider([])):
            response = self.client.post(reverse("marketdata:sync"), {"symbol": "OGDC"}, follow=True)
        self.assertContains(response, "No data returned")
        self.assertEqual(PriceBar.objects.count(), 2)

    def test_sync_requires_permission_and_post(self):
        self.assertEqual(self.client.get(reverse("marketdata:sync")).status_code, 405)
        reader = get_user_model().objects.create_user("reader", password="test-pass")
        self.client.force_login(reader)
        self.assertEqual(
            self.client.post(reverse("marketdata:sync"), {"symbol": "HBL"}).status_code, 403
        )
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_invalid_symbol_does_not_write(self):
        response = self.client.post(reverse("marketdata:sync"), {"symbol": "../bad"})
        self.assertRedirects(response, "/")
        self.assertEqual(Instrument.objects.count(), 1)


class DashboardKpiTests(TestCase):
    """The landing-page "is anything working" KPI row (top model skill,
    signal feed hit-rate) - each source must degrade independently."""

    def setUp(self):
        self.user = get_user_model().objects.create_superuser("viewer", password="test-pass")
        self.client.force_login(self.user)

    def _row(self, name, *, skill, accuracy):
        return SimpleNamespace(
            model=SimpleNamespace(pk=1, name=name), skill=skill, directional_accuracy=accuracy
        )

    def test_kpi_tiles_render_with_data(self):
        rows = [
            self._row("Ridge ENGRO", skill=0.42, accuracy=0.61),
            self._row("HGB HBL", skill=0.10, accuracy=0.55),
        ]
        with (
            patch(
                "modeling.leaderboard.build_leaderboard",
                return_value=SimpleNamespace(ranked=rows),
            ),
            patch(
                "signalfeed.services.trailing_hit_rate",
                return_value={"window_days": 90, "total": 8, "hits": 5, "rate": 0.625},
            ),
        ):
            response = self.client.get("/")
        self.assertContains(response, "TOP MODEL SKILL")
        self.assertContains(response, "Ridge ENGRO")
        self.assertContains(response, "HGB HBL")
        self.assertContains(response, "SIGNAL HIT RATE")
        self.assertContains(response, "62")  # widthratio of 0.625 -> 62%

    def test_kpi_tiles_empty_state_does_not_crash(self):
        with (
            patch(
                "modeling.leaderboard.build_leaderboard",
                return_value=SimpleNamespace(ranked=[]),
            ),
            patch(
                "signalfeed.services.trailing_hit_rate",
                return_value={"window_days": 90, "total": 0, "hits": 0, "rate": None},
            ),
        ):
            response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No scored active models yet")
        self.assertContains(response, "No graded signals yet")

    def test_kpi_tiles_survive_leaderboard_failure(self):
        with (
            patch("modeling.leaderboard.build_leaderboard", side_effect=RuntimeError("boom")),
            patch(
                "signalfeed.services.trailing_hit_rate",
                return_value={"window_days": 90, "total": 0, "hits": 0, "rate": None},
            ),
        ):
            response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No scored active models yet")

    def test_kpi_tiles_survive_signal_feed_failure(self):
        with (
            patch(
                "modeling.leaderboard.build_leaderboard",
                return_value=SimpleNamespace(ranked=[]),
            ),
            patch("signalfeed.services.trailing_hit_rate", side_effect=RuntimeError("boom")),
        ):
            response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No graded signals yet")
