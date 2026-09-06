from django import forms

from marketdata.models import Instrument

from .models import ManualSignal, Strategy
from .registry import registry_choices


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


class StrategyForm(forms.ModelForm):
    """Create / edit a configured strategy instance (what `run_trading_cycle`
    executes). `key` is a dropdown of registered strategy keys - never a free
    text path - and `Strategy.clean()` re-checks it against the registry."""

    key = forms.ChoiceField(choices=[], help_text="Registered strategy class.")
    params = forms.JSONField(
        required=False,
        initial=dict,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text='Keyword args for the strategy class, e.g. {"fast_period": 10}. {} for none.',
    )

    class Meta:
        model = Strategy
        fields = ["name", "key", "params", "instruments", "account", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["key"].choices = registry_choices()
        self.fields["instruments"].widget = forms.CheckboxSelectMultiple()
        self.fields["instruments"].queryset = Instrument.objects.all()

    def clean_params(self):
        value = self.cleaned_data.get("params")
        if value in (None, ""):
            return {}
        if not isinstance(value, dict):
            raise forms.ValidationError("Must be a JSON object.")
        return value


class ManualSignalForm(forms.ModelForm):
    """Operator-entered buy/sell/hold for one instrument on one date, fed
    through the same pipeline as computed strategies via ManualSignalStrategy."""

    class Meta:
        model = ManualSignal
        fields = ["instrument", "date", "action", "note"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "note": forms.Textarea(attrs={"rows": 2}),
        }
