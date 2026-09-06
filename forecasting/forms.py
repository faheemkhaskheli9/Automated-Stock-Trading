"""Config form for the strict-path forecast backtest runner (dashboard D7).

Unlike the ``backtesting`` app there is no persisted config object on this
path - :func:`forecasting.services.run_forecast_backtest` takes kwargs and
writes one flat :class:`~forecasting.models.ForecastBacktestRun`. This form is
therefore a plain :class:`forms.Form` that validates the same fields the
``backtest_predictor`` command exposes, then hands ``cleaned_data`` straight to
the service.
"""

from __future__ import annotations

import json

from django import forms

from marketdata.models import Instrument

from .models import ForecastBacktestRun
from .registry import registered_keys


def _predictor_choices() -> list[tuple[str, str]]:
    return [(key, key) for key in registered_keys()]


def _symbol_choices() -> list[tuple[str, str]]:
    symbols = (
        Instrument.objects.filter(exchange="PSX")
        .order_by("symbol")
        .values_list("symbol", flat=True)
    )
    return [(s, s) for s in symbols]


class ForecastBacktestForm(forms.Form):
    """Everything :func:`run_forecast_backtest` needs for one strict run."""

    name = forms.CharField(max_length=255, required=False, help_text="Optional label.")
    predictor_key = forms.ChoiceField(
        choices=_predictor_choices,
        help_text="A predictor registered in forecasting.registry.",
    )
    symbol = forms.ChoiceField(
        choices=_symbol_choices,
        help_text="One PSX instrument with stored daily history.",
    )
    params = forms.CharField(
        required=False,
        initial="{}",
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text='JSON object of predictor constructor kwargs, e.g. {"alpha": 0.5}.',
    )
    providers = forms.CharField(
        required=False,
        initial="none",
        help_text="Comma-separated research providers, or 'none' for price-only.",
    )
    scheme = forms.ChoiceField(
        choices=ForecastBacktestRun.Scheme.choices,
        initial=ForecastBacktestRun.Scheme.EXPANDING,
    )
    train_span = forms.IntegerField(min_value=1, initial=250, label="Train span (rows)")
    test_span = forms.IntegerField(min_value=1, initial=21, label="Test span (rows)")
    step = forms.IntegerField(min_value=1, initial=21, label="Step (rows)")
    gap = forms.IntegerField(min_value=0, initial=1, label="Embargo gap (rows)")
    start = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    end = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))

    long_threshold = forms.FloatField(initial=0.0)
    allow_short = forms.BooleanField(required=False)
    cost_bps = forms.FloatField(min_value=0, max_value=9_999, initial=0.0)
    initial_cash = forms.FloatField(min_value=0.01, initial=100_000.0)

    def clean_params(self) -> dict:
        raw = (self.cleaned_data.get("params") or "").strip() or "{}"
        try:
            value = json.loads(raw)
        except ValueError as exc:
            raise forms.ValidationError(f"Not valid JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise forms.ValidationError("Must be a JSON object.")
        return value

    def clean_providers(self) -> list[str]:
        raw = (self.cleaned_data.get("providers") or "").strip()
        if not raw or raw.lower() == "none":
            return []
        return [p.strip() for p in raw.split(",") if p.strip()]

    def clean(self):
        data = super().clean()
        start, end = data.get("start"), data.get("end")
        if start and end and start >= end:
            self.add_error("end", "End date must be after the start date.")
        return data

    def run_kwargs(self) -> dict:
        """Map ``cleaned_data`` onto :func:`run_forecast_backtest` kwargs."""
        data = self.cleaned_data
        return {
            "predictor_key": data["predictor_key"],
            "symbol": data["symbol"],
            "start": data["start"],
            "end": data["end"],
            "params": data["params"],
            "provider_keys": data["providers"],
            "scheme": data["scheme"],
            "train_span": data["train_span"],
            "test_span": data["test_span"],
            "step": data["step"],
            "gap": data["gap"],
            "allow_short": data["allow_short"],
            "long_threshold": data["long_threshold"],
            "cost_bps": data["cost_bps"],
            "initial_cash": data["initial_cash"],
            "name": data["name"],
        }
