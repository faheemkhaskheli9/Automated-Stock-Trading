"""Signal delivery fan-out.

Reuses ``execution.notifications``' per-channel senders so order alerts and
trading signals share one delivery path (and one Telegram config). Every
send is best-effort: a channel that is unconfigured or errors is simply left
out of the returned list, never raised.
"""

from __future__ import annotations

import logging

from execution import notifications

logger = logging.getLogger(__name__)

CHANNELS = ("email", "webhook", "telegram")

_SENDERS = {
    "email": notifications.send_email_alert,
    "webhook": notifications.send_webhook_alert,
    "telegram": notifications.send_telegram_alert,
}


def deliver(subject: str, message: str, *, channels=None) -> list[str]:
    """Send ``subject``/``message`` to each requested channel. Returns the
    channels that actually accepted it (order: email, webhook, telegram)."""
    wanted = [c for c in (channels or CHANNELS) if c in _SENDERS]
    logger.info("signalfeed.deliver: %s -> %s", subject, wanted)
    sent: list[str] = []
    for name in CHANNELS:
        if name in wanted and _SENDERS[name](subject, message):
            sent.append(name)
    if not sent:
        logger.info("signalfeed.deliver: no channel delivered %r", subject)
    return sent
