"""Alerting for order fills, rejections, and risk-limit breaches (a
rejection's reason may be a risk check failing) - see docs/PLAN.md, Phase 4.

Both channels (email, webhook) are optional and independent; with neither
configured, an alert is still logged. A failed alert must never break the
trading cycle that triggered it - every failure here is caught and logged,
never raised.
"""

import logging

from django.conf import settings
from django.core.mail import mail_admins

logger = logging.getLogger(__name__)


def send_alert(subject: str, message: str) -> None:
    logger.info("ALERT: %s - %s", subject, message)

    if getattr(settings, "ADMINS", None):
        try:
            mail_admins(subject, message, fail_silently=True)
        except Exception:
            logger.exception("Failed to email admins for alert: %s", subject)

    webhook_url = getattr(settings, "ALERT_WEBHOOK_URL", "")
    if webhook_url:
        _send_webhook(webhook_url, subject, message)


def _send_webhook(url: str, subject: str, message: str) -> None:
    import requests

    try:
        requests.post(url, json={"text": f"*{subject}*\n{message}"}, timeout=5)
    except requests.RequestException:
        logger.exception("Failed to deliver webhook alert: %s", subject)
