from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from ..notifications import send_alert


class SendAlertTests(SimpleTestCase):
    @override_settings(ADMINS=[], ALERT_WEBHOOK_URL="")
    def test_no_channels_configured_does_not_raise(self):
        send_alert("subject", "message")  # just logs - should be a no-op otherwise

    @override_settings(ADMINS=[("Admin", "admin@example.com")], ALERT_WEBHOOK_URL="")
    @patch("execution.notifications.mail_admins")
    def test_emails_admins_when_configured(self, mock_mail_admins):
        send_alert("subject", "message")
        mock_mail_admins.assert_called_once_with("subject", "message", fail_silently=True)

    @override_settings(ADMINS=[], ALERT_WEBHOOK_URL="https://hooks.example.com/webhook")
    @patch("requests.post")
    def test_posts_to_webhook_when_configured(self, mock_post):
        send_alert("subject", "message")
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], "https://hooks.example.com/webhook")
        self.assertIn("subject", kwargs["json"]["text"])

    @override_settings(ADMINS=[], ALERT_WEBHOOK_URL="https://hooks.example.com/webhook")
    @patch("requests.post", side_effect=Exception("network down"))
    def test_webhook_failure_does_not_raise(self, mock_post):
        # requests.RequestException is caught; a raw Exception isn't - use
        # the real exception type so this test reflects actual behavior.
        import requests

        mock_post.side_effect = requests.RequestException("network down")
        send_alert("subject", "message")  # must not raise
