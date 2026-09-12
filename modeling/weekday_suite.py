"""Train one of each applicable estimator on the Monday->Friday
(``weekday_anchored``) target for one instrument, then compare them.

Ties :mod:`modeling.symbol_selection` (pick the best-covered instrument),
:mod:`modeling.training` (fit each estimator via :func:`modeling.services.train_model`)
and each model's own holdout metrics into one call, so "train one of each
model for Monday->Friday and tell me which one is best" is a single action
from the UI or a management command instead of configuring N
:class:`~modeling.models.TradingModel` rows by hand.

Heavy imports (scikit-learn, via ``modeling.training``) are deferred inside
functions, matching ``modeling.services``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from . import services
from .models import TradingModel
from .registry import get_estimator, registered_keys

# A compact but real feature set: recent closes/returns, a few technical
# indicators, and calendar position - enough signal for every estimator type
# without pulling in `research`/`strategy_signal` sources that need extra
# setup (news feeds, a configured Strategy) to produce anything.
DEFAULT_FEATURE_SPEC = [
    # lag 5 is needed by the `seasonal_naive` baseline (default weekly period)
    # as well as the real models' own lag features.
    {"kind": "ohlc", "fields": ["close"], "lags": [0, 1, 2, 3, 4, 5]},
    {"kind": "return", "periods": [1, 5]},
    {"kind": "technical", "names": ["rsi_14", "macd", "sma_10", "sma_20"]},
    {"kind": "calendar", "features": ["weekday", "month"]},
]
TARGET_SPEC = {"type": "weekday_anchored", "entry_weekday": 0, "exit_weekday": 4}

# Meta-estimators need *other* registered estimators named in their own
# params - they aren't a fair "one of each" entry here (that's what
# `modelsearch`'s auto-ensemble step is for). Baselines (naive_last/drift/
# seasonal_naive) are kept in: they're the yardstick the real models need to
# beat.
_EXCLUDED_KEYS = {"voting_ensemble", "stacking_ensemble"}


def suite_estimator_keys() -> list[str]:
    """Every registered, available regression estimator eligible for the
    suite, in a stable order."""
    keys = []
    for key in registered_keys():
        if key in _EXCLUDED_KEYS:
            continue
        spec = get_estimator(key)
        if spec.task != "regression" or not spec.available:
            continue
        keys.append(key)
    return keys


@dataclass
class WeekdaySuiteResult:
    instrument: object | None = None
    symbol_score: object | None = None
    models: list[TradingModel] = field(default_factory=list)
    evaluation: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _model_name(symbol: str, estimator_key: str) -> str:
    return f"Weekday {symbol} - {estimator_key}"


def build_weekday_suite(
    instrument=None,
    *,
    estimators: list[str] | None = None,
    train_start: date | None = None,
    train_end: date | None = None,
    holdout_fraction: float = 0.2,
    created_by=None,
) -> WeekdaySuiteResult:
    """Get-or-create + (re)train one :class:`TradingModel` per estimator key
    for ``instrument``'s Monday->Friday target, then evaluate them.

    ``instrument=None`` auto-picks the best-covered active instrument via
    :mod:`modeling.symbol_selection`. Never raises - a bad estimator key or a
    model that fails ``full_clean``/training is recorded in ``.errors`` (or,
    for a training failure, surfaces as usual on that model's
    ``ModelTrainingRun``) and the rest of the suite still runs.
    """
    from . import symbol_selection

    result = WeekdaySuiteResult()

    if instrument is None:
        scores = symbol_selection.score_instruments()
        viable = [s for s in scores if s.viable]
        if not viable:
            result.errors.append(
                "No active instrument has enough Monday/Friday history to train on."
            )
            return result
        result.symbol_score = viable[0]
        instrument = viable[0].instrument
    else:
        matches = symbol_selection.score_instruments(candidates=[instrument])
        result.symbol_score = matches[0] if matches else None

    result.instrument = instrument

    for key in estimators or suite_estimator_keys():
        try:
            get_estimator(key)
        except KeyError as exc:
            result.errors.append(str(exc))
            continue

        model, _created = TradingModel.objects.get_or_create(
            name=_model_name(instrument.symbol, key),
            defaults={"estimator_key": key},
        )
        model.estimator_key = key
        model.feature_spec = DEFAULT_FEATURE_SPEC
        model.target_spec = TARGET_SPEC
        model.train_start = train_start
        model.train_end = train_end
        model.holdout_fraction = holdout_fraction
        try:
            model.full_clean(exclude=["instruments"])
        except Exception as exc:  # noqa: BLE001 - one bad estimator shouldn't sink the suite
            result.errors.append(f"{key}: {exc}")
            continue
        model.save()
        model.instruments.set([instrument])

        services.train_model(model, start=train_start, end=train_end, created_by=created_by)
        result.models.append(model)

    result.evaluation = evaluate_suite(result.models)
    return result


def evaluate_suite(models: list[TradingModel]) -> list[dict]:
    """Comparison rows (holdout MAE / directional accuracy / skill vs naive)
    for a just-trained batch of models.

    Reads each model's own ``metrics["holdout"]`` rather than
    ``modeling.leaderboard`` (which only scores backfilled ``ModelPrediction``
    rows accumulated over time) so a model trained a moment ago is still
    comparable immediately.
    """
    rows = []
    for model in models:
        holdout = (model.metrics or {}).get("holdout") or {}
        trained = bool(model.trained_at)
        rows.append(
            {
                "model": model,
                "estimator": model.estimator_key,
                "status": "trained" if trained else "failed",
                "n": holdout.get("n"),
                "mae": holdout.get("mae"),
                "rmse": holdout.get("rmse"),
                "directional_accuracy": holdout.get("directional_accuracy"),
                "skill_vs_naive": holdout.get("skill_vs_naive"),
            }
        )

    def _sort_key(row):
        skill = row["skill_vs_naive"]
        return (skill is None, -skill if skill is not None else 0.0)

    rows.sort(key=_sort_key)
    for i, row in enumerate(rows, start=1):
        row["rank"] = i
    return rows
