from django import forms

from modeling.models import ModelTrainingRun, TradingModel

from .models import Backtest


class BacktestConfigForm(forms.Form):
    name = forms.CharField(max_length=255)
    model = forms.ModelChoiceField(
        queryset=TradingModel.objects.all(),
        help_text="Only models with a horizon_close / horizon_return / direction target.",
    )
    fit_mode = forms.ChoiceField(
        choices=Backtest.FitMode.choices,
        initial=Backtest.FitMode.WALK_FORWARD,
        required=False,
        help_text=(
            "walk_forward retrains every fold; frozen_artifact scores the model's already-"
            "trained artifact over every session after it was trained."
        ),
    )
    training_run = forms.ModelChoiceField(
        queryset=ModelTrainingRun.objects.filter(
            status=ModelTrainingRun.Status.SUCCESS
        ).select_related("model"),
        required=False,
        help_text="frozen_artifact only: pin a training run's artifact. Blank = model's latest.",
    )
    scheme = forms.ChoiceField(choices=Backtest.Scheme.choices, initial=Backtest.Scheme.EXPANDING)
    train_span = forms.IntegerField(min_value=1, initial=250, label="Train span (sessions)")
    test_span = forms.IntegerField(min_value=1, initial=21, label="Test span (sessions)")
    step = forms.IntegerField(min_value=1, initial=21, label="Step (sessions)")
    gap = forms.IntegerField(min_value=0, initial=1, label="Embargo gap (sessions)")
    start = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    end = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))

    long_threshold = forms.FloatField(initial=0.0)
    allow_short = forms.BooleanField(required=False)
    initial_cash = forms.FloatField(min_value=0.01, initial=100_000.0)
    commission_bps = forms.FloatField(min_value=0, max_value=9_999, initial=0.0)
    slippage_bps = forms.FloatField(min_value=0, max_value=9_999, initial=0.0)
    is_active = forms.BooleanField(required=False)

    def __init__(self, *args, instance=None, **kwargs):
        self.instance = instance
        if instance is not None and not args and "data" not in kwargs:
            kwargs.setdefault("initial", {})
            kwargs["initial"].update(
                name=instance.name,
                model=instance.model_id,
                fit_mode=instance.fit_mode,
                training_run=instance.training_run_id,
                scheme=instance.scheme,
                train_span=instance.train_span,
                test_span=instance.test_span,
                step=instance.step,
                gap=instance.gap,
                start=instance.start,
                end=instance.end,
                long_threshold=instance.long_threshold,
                allow_short=instance.allow_short,
                initial_cash=instance.initial_cash,
                commission_bps=instance.commission_bps,
                slippage_bps=instance.slippage_bps,
                is_active=instance.is_active,
            )
        super().__init__(*args, **kwargs)

    def save(self) -> Backtest:
        data = self.cleaned_data
        obj = self.instance or Backtest()
        for field in (
            "name",
            "model",
            "fit_mode",
            "training_run",
            "scheme",
            "train_span",
            "test_span",
            "step",
            "gap",
            "start",
            "end",
            "long_threshold",
            "allow_short",
            "initial_cash",
            "commission_bps",
            "slippage_bps",
            "is_active",
        ):
            setattr(obj, field, data[field])
        obj.full_clean(exclude=None)
        obj.save()
        return obj

    def clean(self):
        data = super().clean()
        if self.errors:
            return data
        data["fit_mode"] = data.get("fit_mode") or Backtest.FitMode.WALK_FORWARD
        probe = self.instance or Backtest()
        for field, value in data.items():
            setattr(probe, field, value)
        try:
            probe.full_clean(exclude=["id"])
        except forms.ValidationError as exc:
            for field, msgs in exc.message_dict.items():
                for msg in msgs:
                    self.add_error(None if field == "__all__" else field, msg)
        return data
