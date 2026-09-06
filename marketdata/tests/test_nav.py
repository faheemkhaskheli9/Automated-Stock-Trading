from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class MenubarTests(TestCase):
    """The shared app menubar in marketdata/base.html."""

    def setUp(self):
        self.user = get_user_model().objects.create_superuser("nav", password="test-pass")
        self.client.force_login(self.user)

    def _assert_app_links(self, response):
        self.assertContains(response, 'class="mainnav"')
        self.assertContains(response, reverse("marketdata:dashboard"))
        self.assertContains(response, reverse("strategies:backtest"))
        self.assertContains(response, reverse("modeling:index"))
        self.assertContains(response, reverse("backtesting:index"))
        self.assertContains(response, 'href="/admin/"')
        self.assertContains(response, 'href="/api/"')

    def test_menubar_present_on_dashboard(self):
        self._assert_app_links(self.client.get("/"))

    def test_menubar_shared_across_apps(self):
        self._assert_app_links(self.client.get("/backtesting/"))
        self._assert_app_links(self.client.get("/modeling/"))
        self._assert_app_links(self.client.get("/backtests/"))

    def test_model_backtests_section_marked_active(self):
        content = self.client.get("/backtests/").content.decode()
        marker = f'href="{reverse("backtesting:index")}" aria-current="page"'
        self.assertIn(marker, content)
        self.assertNotIn(
            f'href="{reverse("strategies:backtest")}" aria-current="page"', content
        )

    def test_active_section_marked(self):
        modeling = self.client.get("/modeling/").content.decode()
        marker = f'href="{reverse("modeling:index")}" aria-current="page"'
        self.assertIn(marker, modeling)
        self.assertNotIn(f'href="{reverse("marketdata:dashboard")}" aria-current="page"', modeling)

        dashboard = self.client.get("/").content.decode()
        self.assertIn(f'href="{reverse("marketdata:dashboard")}" aria-current="page"', dashboard)

    def test_no_menubar_when_anonymous(self):
        self.client.logout()
        response = self.client.get("/login/")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'class="mainnav"')
