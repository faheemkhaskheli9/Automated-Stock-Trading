from __future__ import annotations

from django import forms

from marketdata.models import Instrument
from portfolio.models import Account

from .models import Order


class PlaceOrderForm(forms.Form):
    """A single manual paper order. The account choices are restricted to the
    current user's paper accounts; `execution.services.place_order` still runs
    the duplicate guard + `risk.engine.evaluate` before any broker call."""

    account = forms.ModelChoiceField(queryset=Account.objects.none())
    instrument = forms.ModelChoiceField(queryset=Instrument.objects.all())
    side = forms.ChoiceField(choices=Order.Side.choices)
    quantity = forms.IntegerField(min_value=1, max_value=10_000_000)
    confirm = forms.BooleanField(label="I understand this places a paper order now.", required=True)

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        qs = Account.objects.filter(broker=Account.Broker.PAPER)
        if user is not None and not user.is_staff:
            qs = qs.filter(owner=user)
        self.fields["account"].queryset = qs.select_related("owner")
