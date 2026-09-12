import json

from django import forms

from marketdata.models import Instrument
from modeling import features as modeling_features
from modeling import targets as modeling_targets
from modeling.models import TradingModel
from modeling.registry import registry_choices

from . import spaces
from .models import ModelSearch

_SCORE_CHOICES = [("", "auto (task default)")] + [
    (s, s) for s in (*spaces.REGRESSION_SCORES, *spaces.CLASSIFICATION_SCORES)
]


def initial_from_model(base: TradingModel) -> dict:
    """Prefill values for a search seeded from an existing trading model."""
    return {
        "name": f"Search: {base.name}",
        "base_model": base.pk,
        "feature_spec_json": json.dumps(base.feature_spec, indent=2),
        "target_spec_json": json.dumps(base.target_spec, indent=2),
        "instruments": list(base.instruments.values_list("pk", flat=True)),
        "train_start": base.train_start,
        "train_end": base.train_end,
        "holdout_fraction": base.holdout_fraction,
        "estimators": [base.estimator_key],
        "param_grids_json": (
            json.dumps({base.estimator_key: base.estimator_params or {}}, indent=2)
            if base.estimator_params
            else "{}"
        ),
    }


def initial_from_search(search) -> dict:
    space = search.search_space or {}
    return {
        "name": search.name,
        "base_model": search.base_model_id,
        "feature_spec_json": json.dumps(search.feature_spec, indent=2),
        "target_spec_json": json.dumps(search.target_spec, indent=2),
        "instruments": list(search.instruments.values_list("pk", flat=True)),
        "train_start": search.train_start,
        "train_end": search.train_end,
        "holdout_fraction": search.holdout_fraction,
        "estimators": space.get("estimators", []),
        "param_grids_json": json.dumps(space.get("param_grids", {}), indent=2),
        "mode": search.mode,
        "max_candidates": search.max_candidates,
        "random_seed": search.random_seed,
        "auto_ensemble_top_k": search.auto_ensemble_top_k,
        "scoring": search.scoring,
        "scoring_mode": search.scoring_mode,
        "wf_scheme": search.wf_scheme,
        "wf_train_span": search.wf_train_span,
        "wf_test_span": search.wf_test_span,
        "wf_step": search.wf_step,
        "wf_gap": search.wf_gap,
    }


class ModelSearchForm(forms.Form):
    name = forms.CharField(max_length=255)
    base_model = forms.ModelChoiceField(
        queryset=TradingModel.objects.all(),
        required=False,
        help_text="Pick one and press 'Load from base model' to copy its spec / instruments.",
    )
    feature_spec_json = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 5}),
        label="Feature spec JSON",
        help_text="A modeling feature-spec list. Copied from the base model.",
    )
    target_spec_json = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 2}),
        label="Target spec JSON",
        help_text='e.g. {"type": "horizon_close", "horizon": 1}',
    )
    instruments = forms.ModelMultipleChoiceField(queryset=Instrument.objects.all())
    train_start = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    train_end = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    holdout_fraction = forms.FloatField(min_value=0.05, max_value=0.5, initial=0.2)

    estimators = forms.MultipleChoiceField(
        choices=lambda: registry_choices(include_unavailable=False),
        widget=forms.CheckboxSelectMultiple,
        help_text="Every checked estimator is swept; task must match the target.",
    )
    param_grids_json = forms.CharField(
        required=False,
        initial="{}",
        widget=forms.Textarea(attrs={"rows": 5}),
        label="Parameter grids JSON",
        help_text='{"ridge": {"alpha": [0.1, 1.0, 10.0]}}. Estimators absent here use defaults.',
    )
    mode = forms.ChoiceField(
        choices=[("grid", "Grid"), ("random", "Random sample")], initial="grid"
    )
    max_candidates = forms.IntegerField(min_value=1, initial=40)
    random_seed = forms.IntegerField(initial=0)
    auto_ensemble_top_k = forms.IntegerField(
        min_value=0,
        initial=3,
        required=False,
        label="Auto-ensemble top N",
        help_text=(
            "Also try a voting_ensemble of the top N distinct estimators after the sweep "
            "(regression only). 0 or 1 disables."
        ),
    )
    scoring = forms.ChoiceField(choices=_SCORE_CHOICES, required=False)
    scoring_mode = forms.ChoiceField(
        choices=ModelSearch.ScoringMode.choices,
        initial=ModelSearch.ScoringMode.HOLDOUT,
        required=False,
        help_text="Walk-forward refits every candidate per fold - slower, closer to backtesting.",
    )
    wf_scheme = forms.ChoiceField(
        choices=ModelSearch.WfScheme.choices, initial=ModelSearch.WfScheme.EXPANDING, required=False
    )
    wf_train_span = forms.IntegerField(
        min_value=1, initial=250, required=False, label="WF train span"
    )
    wf_test_span = forms.IntegerField(min_value=1, initial=21, required=False, label="WF test span")
    wf_step = forms.IntegerField(min_value=1, initial=21, required=False, label="WF step")
    wf_gap = forms.IntegerField(min_value=0, initial=1, required=False, label="WF gap")

    def clean(self):
        data = super().clean()
        if self.errors:
            return data

        try:
            feature_spec = json.loads(data["feature_spec_json"])
            target_spec = json.loads(data["target_spec_json"])
        except json.JSONDecodeError as exc:
            raise forms.ValidationError(f"Invalid JSON in a spec field: {exc}") from exc

        try:
            modeling_features.validate_spec(feature_spec)
            target_spec = modeling_targets.validate_spec(target_spec)
            task = modeling_targets.task_of(target_spec)
        except ValueError as exc:
            raise forms.ValidationError(str(exc)) from exc

        try:
            param_grids = json.loads(data.get("param_grids_json") or "{}")
        except json.JSONDecodeError as exc:
            self.add_error("param_grids_json", f"Invalid JSON: {exc}")
            return data

        search_space = {"estimators": data.get("estimators", []), "param_grids": param_grids}
        try:
            spaces.validate(search_space, task=task)
        except ValueError as exc:
            self.add_error("param_grids_json", str(exc))
            return data

        if data.get("scoring") and data["scoring"] not in spaces.valid_scores(task):
            self.add_error("scoring", f"Not a valid {task} score.")
            return data

        data["feature_spec"] = feature_spec
        data["target_spec"] = target_spec
        data["search_space"] = search_space

        # Walk-forward config is optional in the payload (e.g. a script/older
        # client posting only the original fields) - fall back to each
        # field's declared default rather than requiring it explicitly.
        for name in (
            "scoring_mode",
            "wf_scheme",
            "wf_train_span",
            "wf_test_span",
            "wf_step",
            "wf_gap",
            "auto_ensemble_top_k",
        ):
            if data.get(name) in (None, ""):
                data[name] = self.fields[name].initial

        return data
