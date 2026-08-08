from django.contrib.auth import get_user_model
from django.test import TestCase

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
