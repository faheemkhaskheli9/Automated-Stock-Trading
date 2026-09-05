from django import forms
from django.utils import timezone


class HistoryForm(forms.Form):
    symbol = forms.RegexField(
        regex=r"^[A-Za-z0-9][A-Za-z0-9.-]{0,31}$",
        max_length=32,
        widget=forms.TextInput(attrs={"placeholder": "e.g. OGDC", "autocomplete": "off"}),
    )
    start = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    end = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))

    def clean_symbol(self):
        return self.cleaned_data["symbol"].upper()

    def clean(self):
        data = super().clean()
        start, end = data.get("start"), data.get("end")
        if start and end and start > end:
            raise forms.ValidationError("Start date must be before or equal to end date.")
        if any(day and day > timezone.localdate() for day in (start, end)):
            raise forms.ValidationError("Choose dates up to today.")
        return data
