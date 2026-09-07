"""The shared server-rendered pager (`marketdata/_pagination.html`).

Operator list pages page their tables through this one partial. These tests
pin its contract: it only shows up once a list overflows one page, it keeps
the current search / filter in the page links, and it supports a named page
parameter so a page hosting more than one table can drive each independently.
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from marketdata.models import Instrument
from research.models import NewsItem
from research.views import HEADLINE_PAGE_SIZE


class PaginationPartialTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("pager", password="pw")

    def setUp(self):
        self.client.force_login(self.user)

    def test_no_pager_when_list_fits_on_one_page(self):
        Instrument.objects.create(symbol="OGDC", exchange="PSX")
        resp = self.client.get(reverse("marketdata:instruments"))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'aria-label="Pagination"')

    def test_pager_appears_and_second_page_differs(self):
        for i in range(120):
            Instrument.objects.create(symbol=f"SYM{i:03d}", exchange="PSX")
        first = self.client.get(reverse("marketdata:instruments"))
        self.assertContains(first, 'aria-label="Pagination"')
        self.assertContains(first, "Page 1 of 3")
        self.assertContains(first, "page=2")

        second = self.client.get(reverse("marketdata:instruments"), {"page": 2})
        self.assertEqual(second.status_code, 200)
        self.assertContains(second, "Page 2 of 3")
        self.assertNotEqual(first.content, second.content)

    def test_pager_keeps_the_active_search_query(self):
        for i in range(60):
            Instrument.objects.create(symbol=f"BANK{i:03d}", exchange="PSX")
        resp = self.client.get(reverse("marketdata:instruments"), {"q": "BANK"})
        self.assertContains(resp, 'aria-label="Pagination"')
        self.assertContains(resp, "q=BANK&amp;page=2")

    def test_out_of_range_page_is_clamped_not_404(self):
        for i in range(60):
            Instrument.objects.create(symbol=f"X{i:03d}", exchange="PSX")
        resp = self.client.get(reverse("marketdata:instruments"), {"page": 999})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Page 2 of 2")

    def test_named_page_param_drives_one_table_independently(self):
        now = timezone.now()
        for i in range(HEADLINE_PAGE_SIZE + 5):
            NewsItem.objects.create(
                symbol="OGDC",
                headline=f"headline {i}",
                url=f"https://example.test/{i}",
                url_hash=f"hash-{i}",
                published_at=now - timedelta(days=i),
            )
        resp = self.client.get(reverse("research:index"))
        self.assertEqual(resp.status_code, 200)
        # The headlines table pages on ``news``, not the shared ``page`` name.
        self.assertContains(resp, "news=2")

        page_two = self.client.get(reverse("research:index"), {"news": 2})
        self.assertEqual(page_two.status_code, 200)
        self.assertContains(page_two, "headline 26")
