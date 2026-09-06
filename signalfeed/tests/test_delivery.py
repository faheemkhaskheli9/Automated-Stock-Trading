from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from execution import notifications
from signalfeed.delivery import deliver


class DeliverTests(SimpleTestCase):
    @override_settings(ADMINS=[], ALERT_WEBHOOK_URL="", TELEGRAM_BOT_TOKEN="", TELEGRAM_CHAT_ID="")
    def test_nothing_configured_returns_empty(self):
        self.assertEqual(deliver("s", "m"), [])

    @override_settings(
        ADMINS=[("A", "a@x.com")],
        ALERT_WEBHOOK_URL="https://hook.example/x",
        TELEGRAM_BOT_TOKEN="tok",
        TELEGRAM_CHAT_ID="42",
    )
    @patch("execution.notifications.mail_admins")
    @patch("requests.post")
    def test_all_three_channels(self, mock_post, mock_mail):
        sent = deliver("subj", "body")
        self.assertEqual(sent, ["email", "webhook", "telegram"])
        mock_mail.assert_called_once()
        # one webhook POST + one telegram POST
        self.assertEqual(mock_post.call_count, 2)
        telegram_call = mock_post.call_args_list[-1]
        self.assertIn("api.telegram.org", telegram_call.args[0])
        self.assertEqual(telegram_call.kwargs["json"]["chat_id"], "42")

    @override_settings(
        ADMINS=[], ALERT_WEBHOOK_URL="", TELEGRAM_BOT_TOKEN="tok", TELEGRAM_CHAT_ID="42"
    )
    def test_channel_filter_restricts(self):
        with patch("requests.post") as mock_post:
            deliver("s", "m", channels=["email"])  # telegram configured but not requested
            mock_post.assert_not_called()

    @override_settings(
        ADMINS=[], ALERT_WEBHOOK_URL="", TELEGRAM_BOT_TOKEN="tok", TELEGRAM_CHAT_ID="42"
    )
    @patch("requests.post")
    def test_telegram_failure_is_swallowed(self, mock_post):
        import requests

        mock_post.side_effect = requests.RequestException("boom")
        self.assertEqual(deliver("s", "m"), [])  # no raise, nothing delivered

    @override_settings(TELEGRAM_BOT_TOKEN="tok", TELEGRAM_CHAT_ID="42")
    @patch("requests.post")
    def test_send_telegram_alert_direct(self, mock_post):
        self.assertTrue(notifications.send_telegram_alert("s", "m"))
