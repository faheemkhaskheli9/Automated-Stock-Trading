from __future__ import annotations

from django import forms

from .models import CompanyFundamental


class SyncForm(forms.Form):
    """Trigger a point-in-time snapshot build (and, optionally, a news
    ingest) for one symbol from the UI."""

    symbol = forms.CharField(max_length=32)
    exchange = forms.CharField(max_length=16, initial="PSX")
    as_of = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
        help_text="Build the snapshot as of this date. Blank = now.",
    )
    ingest_news = forms.BooleanField(
        required=False,
        help_text="Also pull configured news feeds first (network).",
    )

    def clean_symbol(self):
        return self.cleaned_data["symbol"].strip().upper()

    def clean_exchange(self):
        return (self.cleaned_data.get("exchange") or "PSX").strip().upper()


class FundamentalForm(forms.ModelForm):
    """Manual point-in-time fundamentals entry - the CSV loader's UI twin."""

    ratios = forms.JSONField(
        initial=dict,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text='JSON object, e.g. {"pe": 8.1, "pb": 1.2, "eps": 4.3}.',
    )

    class Meta:
        model = CompanyFundamental
        fields = ["symbol", "exchange", "as_of_report_date", "ratios", "source"]
        widgets = {"as_of_report_date": forms.DateInput(attrs={"type": "date"})}

    def clean_symbol(self):
        return self.cleaned_data["symbol"].strip().upper()

    def clean_ratios(self):
        value = self.cleaned_data.get("ratios")
        if value in (None, ""):
            return {}
        if not isinstance(value, dict):
            raise forms.ValidationError("Must be a JSON object.")
        return value
