import json

from django import forms

from marketdata.models import Instrument
from strategies.models import Strategy

from . import features, targets
from .registry import get_estimator, registry_choices


def _int_csv(raw: str, name: str) -> list[int]:
    if not raw or not raw.strip():
        return []
    try:
        return [int(part) for part in raw.replace(" ", "").split(",") if part]
    except ValueError as exc:
        raise forms.ValidationError(f"{name} must be a comma-separated list of integers") from exc


class ModelConfigForm(forms.Form):
    name = forms.CharField(max_length=255)
    estimator = forms.ChoiceField(choices=registry_choices)
    estimator_params = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text='JSON, e.g. {"alpha": 0.5}. Blank = estimator defaults.',
    )

    # --- structured feature builder (ignored when the JSON override is set) --
    ohlc_fields = forms.MultipleChoiceField(
        required=False,
        widget=forms.CheckboxSelectMultiple,
        choices=[(f, f) for f in features.OHLC_FIELDS],
        initial=["open", "high", "low", "close"],
    )
    ohlc_lags = forms.CharField(required=False, initial="0,1,2", label="OHLC lags")
    return_periods = forms.CharField(required=False, initial="1,5", label="Return periods")
    technical = forms.BooleanField(required=False, label="All technical indicators")
    strategy_signal = forms.ModelChoiceField(
        required=False,
        queryset=Strategy.objects.all(),
        label="Saved strategy signal",
    )
    calendar_features = forms.MultipleChoiceField(
        required=False,
        widget=forms.CheckboxSelectMultiple,
        choices=[(f, f) for f in features.CALENDAR_FEATURES],
    )
    feature_spec_json = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
        label="Feature spec JSON (advanced override)",
        help_text="If set, this raw list replaces every structured choice above.",
    )

    # --- target ---------------------------------------------------------
    target_type = forms.ChoiceField(choices=[(t, t) for t in targets.TARGET_TYPES])
    horizon = forms.IntegerField(required=False, min_value=1, initial=1)
    entry_weekday = forms.ChoiceField(
        required=False,
        choices=list(enumerate(targets.WEEKDAYS)),
        initial=0,
    )
    exit_weekday = forms.ChoiceField(
        required=False,
        choices=list(enumerate(targets.WEEKDAYS)),
        initial=4,
    )
    steps = forms.IntegerField(required=False, min_value=2, initial=3)

    # --- data / split -------------------------------------------------
    instruments = forms.ModelMultipleChoiceField(queryset=Instrument.objects.all())
    train_start = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    train_end = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    holdout_fraction = forms.FloatField(min_value=0.05, max_value=0.5, initial=0.2)

    def __init__(self, *args, instance=None, **kwargs):
        self.instance = instance
        if instance is not None and not args and "data" not in kwargs:
            kwargs.setdefault("initial", {})
            kwargs["initial"].update(
                name=instance.name,
                estimator=instance.estimator_key,
                estimator_params=(
                    json.dumps(instance.estimator_params) if instance.estimator_params else ""
                ),
                feature_spec_json=json.dumps(instance.feature_spec, indent=2),
                target_type=(instance.target_spec or {}).get("type", "horizon_close"),
                horizon=(instance.target_spec or {}).get("horizon", 1),
                entry_weekday=(instance.target_spec or {}).get("entry_weekday", 0),
                exit_weekday=(instance.target_spec or {}).get("exit_weekday", 4),
                steps=(instance.target_spec or {}).get("steps", 3),
                train_start=instance.train_start,
                train_end=instance.train_end,
                holdout_fraction=instance.holdout_fraction,
                instruments=list(instance.instruments.values_list("pk", flat=True)),
            )
        super().__init__(*args, **kwargs)

    def _params(self):
        raw = (self.cleaned_data.get("estimator_params") or "").strip()
        if not raw:
            return {}
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise forms.ValidationError({"estimator_params": f"Invalid JSON: {exc}"}) from exc
        if not isinstance(value, dict):
            raise forms.ValidationError({"estimator_params": "Must be a JSON object"})
        return value

    def _feature_spec(self):
        raw = (self.cleaned_data.get("feature_spec_json") or "").strip()
        if raw:
            try:
                return json.loads(raw)
            except json.JSONDecodeError as exc:
                raise forms.ValidationError({"feature_spec_json": f"Invalid JSON: {exc}"}) from exc

        spec = []
        if self.cleaned_data.get("ohlc_fields"):
            spec.append(
                {
                    "kind": "ohlc",
                    "fields": self.cleaned_data["ohlc_fields"],
                    "lags": _int_csv(self.cleaned_data.get("ohlc_lags"), "OHLC lags") or [0],
                }
            )
        periods = _int_csv(self.cleaned_data.get("return_periods"), "Return periods")
        if periods:
            spec.append({"kind": "return", "periods": periods})
        if self.cleaned_data.get("technical"):
            spec.append({"kind": "technical"})
        if self.cleaned_data.get("strategy_signal"):
            spec.append(
                {
                    "kind": "strategy_signal",
                    "strategy_id": self.cleaned_data["strategy_signal"].pk,
                }
            )
        if self.cleaned_data.get("calendar_features"):
            spec.append({"kind": "calendar", "features": self.cleaned_data["calendar_features"]})
        return spec

    def _target_spec(self):
        ttype = self.cleaned_data["target_type"]
        if ttype in ("horizon_close", "horizon_return", "direction"):
            return {"type": ttype, "horizon": self.cleaned_data.get("horizon") or 1}
        if ttype == "weekday_anchored":
            return {
                "type": ttype,
                "entry_weekday": int(self.cleaned_data.get("entry_weekday") or 0),
                "exit_weekday": int(self.cleaned_data.get("exit_weekday") or 4),
            }
        return {"type": "multistep", "steps": self.cleaned_data.get("steps") or 3}

    def clean(self):
        data = super().clean()
        if self.errors:
            return data
        try:
            params = self._params()
            feature_spec = features.validate_spec(self._feature_spec())
            target_spec = targets.validate_spec(self._target_spec())
        except (ValueError, forms.ValidationError) as exc:
            message = exc.message_dict if hasattr(exc, "message_dict") else {"__all__": [str(exc)]}
            for field, msgs in message.items():
                for msg in msgs if isinstance(msgs, list) else [msgs]:
                    self.add_error(None if field == "__all__" else field, msg)
            return data

        est = get_estimator(data["estimator"])
        try:
            est.coerce_params(params)
        except ValueError as exc:
            self.add_error("estimator_params", str(exc))
            return data
        if est.task != targets.task_of(target_spec):
            self.add_error(
                "estimator",
                f"Estimator is for {est.task}; the target is a {targets.task_of(target_spec)} "
                "problem.",
            )
            return data

        data["params_obj"] = params
        data["feature_spec"] = feature_spec
        data["target_spec"] = target_spec
        return data


class PredictForm(forms.Form):
    instrument = forms.ModelChoiceField(queryset=Instrument.objects.none())
    as_of = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    target_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
        help_text="Required unless the target is weekday-anchored (then it is derived).",
    )

    def __init__(self, *args, model=None, **kwargs):
        super().__init__(*args, **kwargs)
        if model is not None:
            self.fields["instrument"].queryset = model.instruments.all()
