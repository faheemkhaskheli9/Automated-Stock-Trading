"""Guards for the shared 'PSX Observatory' design system.

The operator UI is one authored stylesheet (marketdata/static/marketdata/
dashboard.css) plus server-rendered templates that all extend
marketdata/base.html. These tests keep it that way: no per-page ``<style>``
blocks or ad-hoc ``style="..."`` attributes creeping back in, no revived
per-app stylesheets, and the token / dark-mode contract intact.
"""

from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase

CSS = Path(settings.BASE_DIR) / "marketdata" / "static" / "marketdata" / "dashboard.css"

# Pages that render with an empty database and were fully migrated to shared
# component classes (no inline styling of any kind).
CLEAN_PAGES = [
    "/",
    "/instruments/",
    "/research/",
    "/signals/",
    "/signals/watchlist/",
    "/portfolio/",
    "/trading/",
    "/risk/",
    "/modeling/",
    "/modeling/leaderboard/",
    "/modeling/estimators/",
    "/backtests/",
    "/forecast-backtests/",
    "/backtesting/",
    "/profile/",
]

RETIRED_TOKENS = [
    "pnl-pos",
    "pnl-neg",
    "st-on",
    "st-off",
    "gate-pass",
    "gate-block",
    "wl-actions",
    "st-actions",
    "sig-actions",
    "model-form",
    "bt-form",
    "pf-kpi",
    'href="{% static',
]


class StylesheetContractTests(TestCase):
    def test_single_stylesheet_defines_tokens_and_dark_mode(self):
        css = CSS.read_text(encoding="utf-8")
        for token in ("--bg:", "--surface:", "--text:", "--brand:", "--pos:", "--neg:"):
            self.assertIn(token, css, f"missing design token {token}")
        self.assertIn("@media (prefers-color-scheme: dark)", css)
        self.assertIn(".is-pos", css)
        self.assertIn(".is-neg", css)

    def test_retired_per_app_stylesheets_are_gone(self):
        base = Path(settings.BASE_DIR)
        for dead in (
            "modeling/static/modeling/modeling.css",
            "backtesting/static/backtesting/backtesting.css",
            "strategies/static/strategies/backtest.css",
        ):
            self.assertFalse((base / dead).exists(), f"{dead} should be deleted")


class RenderedPageHygieneTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser("ui", password="pw")
        self.client.force_login(self.user)

    def test_pages_carry_no_inline_styling_and_use_shared_classes(self):
        for path in CLEAN_PAGES:
            with self.subTest(path=path):
                resp = self.client.get(path)
                self.assertEqual(resp.status_code, 200)
                body = resp.content.decode()
                self.assertNotIn("<style", body)
                self.assertNotIn('style="', body)
                for retired in RETIRED_TOKENS:
                    self.assertNotIn(retired, body)

    def test_shared_component_classes_are_in_use(self):
        body = self.client.get("/signals/").content.decode()
        self.assertIn("action-row", body)
        self.assertIn('class="kpi"', body)

    def test_base_template_declares_color_scheme(self):
        body = self.client.get("/").content.decode()
        self.assertIn('name="color-scheme"', body)
