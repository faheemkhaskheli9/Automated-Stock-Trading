"""Skill-vs-naive badge helpers, shared by the ``backtesting`` and
``forecasting`` walk-forward runner pages.

``skill_vs_naive`` (``1 - mae / naive_mae``) is the headline number on both
pages: positive means the model beats a "close unchanged" forecast. Rendered
as a bare float it takes a second to parse; as a colour it reads instantly.
"""

from __future__ import annotations

from django import template
from django.utils.html import format_html

register = template.Library()

_DASH = "—"


def _state(value) -> str:
    """``good`` (beats naive), ``bad`` (doesn't), or ``none`` (no score)."""
    if value is None:
        return "none"
    try:
        num = float(value)
    except (TypeError, ValueError):
        return "none"
    return "good" if num > 0 else "bad"


@register.filter
def skill_state(value) -> str:
    """CSS state word for a skill-vs-naive number - ``good``/``bad``/``none``."""
    return _state(value)


@register.simple_tag
def skill_badge(value, leaky: bool = False):
    """Render a skill-vs-naive score as a colour-coded pill.

    Positive skill is green, zero-or-worse is red, a missing score is a
    neutral dash. ``leaky=True`` overrides the colour with an amber warning
    tint - an implausibly high score is a red flag, not a win.
    """
    state = _state(value)
    if state == "none":
        return format_html('<span class="skill-badge none">{}</span>', _DASH)
    label = format(float(value), ".3f")
    if leaky:
        return format_html(
            '<span class="skill-badge leaky" '
            'title="Implausibly high - investigate for leakage">{}</span>',
            label,
        )
    return format_html('<span class="skill-badge {}">{}</span>', state, label)
