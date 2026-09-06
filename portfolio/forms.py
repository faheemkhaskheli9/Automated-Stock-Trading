from __future__ import annotations

from django import forms

from .models import Account


class AccountForm(forms.ModelForm):
    """Create / edit one of the current user's accounts. `owner` is set from
    the request, never the form; broker choices come from the model and only
    ``paper`` exists today."""

    class Meta:
        model = Account
        fields = ["name", "account_type", "broker", "currency", "cash_balance"]

    def __init__(self, *args, owner=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._owner = owner

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        qs = Account.objects.filter(owner=self._owner, name=name)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("You already have an account with this name.")
        return name
