from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from marketdata.models import Instrument
from modeling.models import TradingModel


class ModelSearch(models.Model):
    """A parameter/model sweep: one feature+target spec, a set of instruments
    and a train window (all copied from a base :class:`~modeling.models.TradingModel`),
    plus a space of estimators x hyper-parameter grids to compare.

    The dataset-input field names are deliberately identical to
    ``TradingModel`` so a ``ModelSearch`` instance can be handed straight to
    ``modeling.dataset.build_dataset``.
    """

    class Mode(models.TextChoices):
        GRID = "grid", "Grid (every combination)"
        RANDOM = "random", "Random sample"

    class ScoringMode(models.TextChoices):
        HOLDOUT = "holdout", "Trailing holdout"
        WALK_FORWARD = "walk_forward", "Walk-forward (refit per fold)"

    class WfScheme(models.TextChoices):
        EXPANDING = "expanding", "Expanding window"
        ROLLING = "rolling", "Rolling window"

    name = models.CharField(max_length=255)
    base_model = models.ForeignKey(
        TradingModel,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="model_searches",
        help_text="The trading model this search was seeded from (provenance only).",
    )
    feature_spec = models.JSONField(default=list, blank=True)
    target_spec = models.JSONField(default=dict, blank=True)
    instruments = models.ManyToManyField(Instrument, related_name="model_searches", blank=True)
    train_start = models.DateField(null=True, blank=True)
    train_end = models.DateField(null=True, blank=True)
    holdout_fraction = models.FloatField(
        default=0.2, help_text="Trailing fraction of rows scored for every candidate (0.05-0.5)."
    )
    search_space = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "{'estimators': [...], 'param_grids': {key: {param: [values]}}}. "
            "An estimator with no grid entry is tried once at its defaults."
        ),
    )
    mode = models.CharField(max_length=8, choices=Mode.choices, default=Mode.GRID)
    max_candidates = models.PositiveIntegerField(
        default=40, help_text="Cap on candidates evaluated in one run."
    )
    random_seed = models.IntegerField(default=0)
    scoring = models.CharField(
        max_length=32,
        blank=True,
        help_text="Metric key to rank by. Blank = the task default.",
    )
    scoring_mode = models.CharField(
        max_length=12,
        choices=ScoringMode.choices,
        default=ScoringMode.HOLDOUT,
        help_text=(
            "Holdout: one trailing split, fast. Walk-forward: refit every candidate on each "
            "backtesting.walkforward fold and pool the out-of-sample predictions - slower "
            "(candidates x folds fits) but the accuracy read the single holdout can diverge from."
        ),
    )
    wf_scheme = models.CharField(
        max_length=12, choices=WfScheme.choices, default=WfScheme.EXPANDING
    )
    wf_train_span = models.PositiveIntegerField(
        default=250, help_text="Walk-forward only. Sessions of training history per fold."
    )
    wf_test_span = models.PositiveIntegerField(
        default=21, help_text="Walk-forward only. Sessions scored per fold before the next refit."
    )
    wf_step = models.PositiveIntegerField(
        default=21, help_text="Walk-forward only. Sessions the window advances between folds."
    )
    wf_gap = models.PositiveIntegerField(
        default=1,
        help_text="Walk-forward only. Embargo sessions between a fold's train end and test start.",
    )
    best_result = models.ForeignKey(
        "ModelSearchResult",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "model searches"

    def __str__(self):
        return self.name

    def clean(self):
        from modeling import features, targets

        from . import spaces

        errors = {}
        try:
            features.validate_spec(self.feature_spec)
        except ValueError as exc:
            errors["feature_spec"] = str(exc)

        task = None
        try:
            task = targets.task_of(self.target_spec)
        except ValueError as exc:
            errors["target_spec"] = str(exc)

        if task is not None:
            try:
                spaces.validate(self.search_space, task=task)
            except ValueError as exc:
                errors["search_space"] = str(exc)
            if self.scoring and self.scoring not in spaces.valid_scores(task):
                errors["scoring"] = (
                    f"{self.scoring!r} is not a valid {task} score; "
                    f"choose from {list(spaces.valid_scores(task))}"
                )

        if not 0.05 <= self.holdout_fraction <= 0.5:
            errors["holdout_fraction"] = "Must be between 0.05 and 0.5."
        if self.max_candidates < 1:
            errors["max_candidates"] = "Must be at least 1."

        for field in ("wf_train_span", "wf_test_span", "wf_step"):
            if getattr(self, field) < 1:
                errors[field] = "Must be at least 1 session."

        if errors:
            raise ValidationError(errors)

    @property
    def task(self) -> str:
        from modeling import targets

        return targets.task_of(self.target_spec)

    def score_key(self) -> str:
        from . import spaces

        return self.scoring or spaces.DEFAULT_SCORE[self.task]


class ModelSearchRun(models.Model):
    """One execution of a search. Mirrors ``modeling.ModelTrainingRun`` -
    ``modelsearch.search.run_search`` never raises; every outcome lands here."""

    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"

    search = models.ForeignKey(ModelSearch, on_delete=models.CASCADE, related_name="runs")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.RUNNING)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    candidates_total = models.PositiveIntegerField(null=True, blank=True)
    candidates_ok = models.PositiveIntegerField(null=True, blank=True)
    candidates_failed = models.PositiveIntegerField(null=True, blank=True)
    dataset_rows = models.PositiveIntegerField(null=True, blank=True)
    feature_count = models.PositiveIntegerField(null=True, blank=True)
    error = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return f"{self.search.name} run #{self.pk} ({self.status})"


class ModelSearchResult(models.Model):
    """One evaluated candidate: an estimator + a concrete param set, scored on
    the search's trailing holdout, with its fit/predict cost recorded."""

    class Status(models.TextChoices):
        OK = "ok", "OK"
        FAILED = "failed", "Failed"

    search = models.ForeignKey(ModelSearch, on_delete=models.CASCADE, related_name="all_results")
    run = models.ForeignKey(ModelSearchRun, on_delete=models.CASCADE, related_name="results")
    estimator_key = models.CharField(max_length=64)
    estimator_params = models.JSONField(default=dict, blank=True)
    params_hash = models.CharField(max_length=40)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.OK)
    score = models.FloatField(null=True, blank=True)
    metrics = models.JSONField(default=dict, blank=True)
    fit_seconds = models.FloatField(null=True, blank=True)
    predict_seconds = models.FloatField(null=True, blank=True)
    predict_latency_ms = models.FloatField(
        null=True, blank=True, help_text="Holdout predict wall time per row, milliseconds."
    )
    model_size_bytes = models.PositiveIntegerField(null=True, blank=True)
    wf_folds = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Walk-forward mode only: folds pooled into this candidate's score/metrics.",
    )
    rank = models.PositiveIntegerField(null=True, blank=True)
    is_pareto = models.BooleanField(
        default=False, help_text="Not dominated on (score, fit time, predict latency, size)."
    )
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["rank", "-score"]
        constraints = [
            models.UniqueConstraint(fields=["run", "params_hash"], name="unique_candidate_per_run")
        ]

    def __str__(self):
        return f"{self.estimator_key} {self.estimator_params} (rank {self.rank})"
