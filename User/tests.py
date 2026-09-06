from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import UserProfile


class UserProfileTests(TestCase):
    def test_defaults(self):
        user = get_user_model().objects.create_user(username="trader", password="pw")
        profile = UserProfile.objects.create(user=user)

        self.assertEqual(profile.risk_tolerance, UserProfile.RiskTolerance.MODERATE)
        self.assertEqual(str(profile), f"Trading profile for {user}")

    def test_one_profile_per_user(self):
        user = get_user_model().objects.create_user(username="trader", password="pw")
        UserProfile.objects.create(user=user)

        with self.assertRaises(Exception):
            UserProfile.objects.create(user=user)


class ProfileViewTests(TestCase):
    def test_requires_login(self):
        resp = self.client.get(reverse("user:profile"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("login", resp["Location"])

    def test_get_creates_profile_on_first_visit(self):
        user = get_user_model().objects.create_user(username="trader", password="pw")
        self.client.force_login(user)
        resp = self.client.get(reverse("user:profile"))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(UserProfile.objects.filter(user=user).exists())

    def test_post_updates_limits(self):
        user = get_user_model().objects.create_user(username="trader", password="pw")
        self.client.force_login(user)
        resp = self.client.post(
            reverse("user:profile"),
            {
                "risk_tolerance": "aggressive",
                "max_daily_loss_pct": "5.0",
                "max_position_size_pct": "25.0",
            },
        )
        self.assertEqual(resp.status_code, 302)
        profile = UserProfile.objects.get(user=user)
        self.assertEqual(profile.risk_tolerance, "aggressive")
        self.assertEqual(float(profile.max_position_size_pct), 25.0)
