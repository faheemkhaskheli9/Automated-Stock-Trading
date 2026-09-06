from django import forms

from marketdata.models import Instrument

from .models import Strategy


class BacktestForm(forms.Form):
    instrument = forms.ModelChoiceField(queryset=Instrument.objects.all())
    model = forms.ChoiceField(label="Trading model")
    start = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    end = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    initial_cash = forms.DecimalField(min_value=1, max_value=1_000_000_000, initial=100_000)
    commission_bps = forms.DecimalField(
        min_value=0, max_value=500, initial=10, label="Commission (bps)"
    )
    slippage_bps = forms.DecimalField(min_value=0, max_value=500, initial=5, label="Slippage (bps)")
    fast_period = forms.IntegerField(min_value=2, max_value=250, initial=10)
    slow_period = forms.IntegerField(min_value=3, max_value=500, initial=30)

    def __init__(self, *args, allow_saved=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.saved = Strategy.objects.all() if allow_saved else Strategy.objects.none()
        self.fields["model"].choices = [
            ("ma_crossover", "Moving average crossover"),
            ("rsi", "RSI · 14 / 30 / 70"),
        ] + [(f"saved:{s.pk}", s.name) for s in self.saved]

    def clean(self):
        data = super().clean()
        if data.get("start") and data.get("end") and data["start"] > data["end"]:
            self.add_error("end", "End date must be on or after start date.")
        if data.get("model") == "ma_crossover" and data.get("fast_period", 0) >= data.get(
            "slow_period", 501
        ):
            self.add_error("slow_period", "Slow period must be greater than fast period.")
        return data
