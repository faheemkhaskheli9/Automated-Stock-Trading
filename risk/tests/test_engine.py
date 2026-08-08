from decimal import Decimal

from django.test import TestCase

from portfolio.tests.factories import make_account, make_instrument
from strategies.signals import Action
from User.models import UserProfile

from ..engine import evaluate
from ..models import RiskDecision


class EvaluateTests(TestCase):
    def test_approves_and_logs_a_reasonable_buy(self):
        account = make_account(cash_balance=100_000)
        instrument = make_instrument()

        result = evaluate(account, instrument, Action.BUY, 10, Decimal("100"))

        self.assertTrue(result.approved)
        decision = RiskDecision.objects.get()
        self.assertTrue(decision.approved)
        self.assertEqual(decision.account, account)
        self.assertEqual(decision.action, "buy")

    def test_uses_default_thresholds_when_no_user_profile_exists(self):
        account = make_account(cash_balance=1000)
        instrument = make_instrument()

        # 100 shares * 100 = 10,000 way over 10% of 1000 equity -> rejected
        result = evaluate(account, instrument, Action.BUY, 100, Decimal("100"))

        self.assertFalse(result.approved)

    def test_uses_the_account_owner_s_risk_profile_when_present(self):
        account = make_account(cash_balance=100_000)
        instrument = make_instrument()
        UserProfile.objects.create(
            user=account.owner, max_daily_loss_pct=Decimal("2"), max_position_size_pct=Decimal("50")
        )

        # 300 shares * 100 = 30,000 = 30% of equity, within the profile's 50% cap
        result = evaluate(account, instrument, Action.BUY, 300, Decimal("100"))

        self.assertTrue(result.approved)

    def test_rejection_is_logged_with_a_reason(self):
        account = make_account(cash_balance=1000)
        instrument = make_instrument()

        evaluate(account, instrument, Action.BUY, 100, Decimal("100"))

        decision = RiskDecision.objects.get()
        self.assertFalse(decision.approved)
        self.assertNotEqual(decision.reason, "")
