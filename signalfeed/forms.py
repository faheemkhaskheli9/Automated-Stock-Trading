"""Operator forms for the signal feed UI.

Kept deliberately thin: :class:`WatchItemForm` is a ``ModelForm`` and leans on
:meth:`signalfeed.models.WatchItem.clean` (target-type / range checks) and the
model's unique constraint for validation, exactly like the admin does.
"""

from __future__ import annotations

from django import forms

from modeling.models import TradingModel

from .models import SUPPORTED_TARGETS, WatchItem


def eligible_models():
    """Trading models whose target this app can turn into a weekly call."""
    ids = [
        m.pk
        for m in TradingModel.objects.all()
        if isinstance(m.target_spec, dict) and m.target_spec.get("type") in SUPPORTED_TARGETS
    ]
    return TradingModel.objects.filter(pk__in=ids).order_by("name")


class WatchItemForm(forms.ModelForm):
    class Meta:
        model = WatchItem
        fields = [
            "instrument",
            "trading_model",
            "is_active",
            "min_directional_accuracy",
            "min_skill",
            "min_expected_move_pct",
            "notes",
        ]
        widgets = {"notes": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["trading_model"].queryset = eligible_models()
        self.fields["trading_model"].help_text = (
            "Only models with a weekday-anchored / horizon-close / horizon-return / "
            "direction target are listed."
        )
