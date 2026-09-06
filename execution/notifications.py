"""Alerting for order fills, rejections, and risk-limit breaches (a
rejection's reason may be a risk check failing) - see docs/PLAN.md, Phase 4.

Three channels (email, generic webhook, Telegram bot), all optional and
independent; with none configured, an alert is still logged. A failed alert
must never break the trading cycle that triggered it - every failure here is
caught and logged, never raised. The per-channel senders are also reused by
``signalfeed.delivery`` so trading signals go out the same way.
"""

import logging

from django.conf import settings
from django.core.mail import mail_admins

logger = logging.getLogger(__name__)


def send_alert(subject: str, message: str) -> None:
    logger.info("ALERT: %s - %s", subject, message)
    send_email_alert(subject, message)
    send_webhook_alert(subject, message)
    send_telegram_alert(subject, message)


def send_email_alert(subject: str, message: str) -> bool:
    if not getattr(settings, "ADMINS", None):
        return False
    try:
        mail_admins(subject, message, fail_silently=True)
        return True
    except Exception:  # noqa: BLE001 - alerting must never raise
        logger.exception("Failed to email admins for alert: %s", subject)
        return False


def send_webhook_alert(subject: str, message: str) -> bool:
    url = getattr(settings, "ALERT_WEBHOOK_URL", "")
    if not url:
        return False

    import requests

    try:
        requests.post(url, json={"text": f"*{subject}*\n{message}"}, timeout=5)
        return True
    except requests.RequestException:
        logger.exception("Failed to deliver webhook alert: %s", subject)
        return False


def send_telegram_alert(subject: str, message: str) -> bool:
    token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
    chat_id = getattr(settings, "TELEGRAM_CHAT_ID", "")
    if not (token and chat_id):
        return False

    import requests

    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": f"{subject}\n\n{message}",
                "disable_web_page_preview": True,
            },
            timeout=5,
        )
        resp.raise_for_status()
        return True
    except requests.RequestException:
        logger.exception("Failed to deliver Telegram alert: %s", subject)
        return False
