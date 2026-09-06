"""Walk-forward orchestration for `forecasting.BasePredictor` predictors.

``walk_forward`` assembles the point-in-time training frame once (features for
row *t* only ever see history ``<= t``), then for each fold:

* slices a contiguous training window and drops any row whose label was not
  observable strictly before the fold's first test decision,
* fits a **fresh** predictor instance on that slice only,
* asks it for one forecast per test row (a label-free ``PredictionFrame``),
* scores predicted-vs-actual next-session closes.

No fitted object, scaler or imputer ever crosses the train/test boundary; the
frame handed to ``predict_series`` never contains the target bar.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

import pandas as pd

from ..base import PredictionFrame, TrainingFrame
from ..features import DEFAULT_PROVIDERS, assemble_training_frame
from ..registry import get_predictor_class
from .metrics import regression_scores, trading_translation
from .walkforward import EXPANDING, generate_folds


@dataclass(frozen=True)
class FoldReport:
    index: int
    train_start: date
    train_end: date
    test_start: date
    test_end: date
    n_train: int
    n_test: int
    metrics: dict


@dataclass
class WalkForwardResult:
    predictor_key: str
    params: dict
    symbol: str
    exchange: str
    scheme: str
    folds: list[FoldReport] = field(default_factory=list)
    predictions: list[dict] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    naive_metrics: dict = field(default_factory=dict)
    trading: dict = field(default_factory=dict)
    skipped_folds: list[dict] = field(default_factory=list)

    @property
    def skill_vs_naive(self) -> float | None:
        return self.metrics.get("skill_vs_naive")

    def fold_table(self) -> str:
        head = (
            f"{'fold':>4}  {'test window':<25}  {'n':>4}  {'mae':>10}  {'skill':>8}  {'dir.acc':>8}"
        )
        rows = [head, "-" * len(head)]
        for f in self.folds:
            rows.append(
                f"{f.index:>4}  {f.test_start} .. {f.test_end}  {f.n_test:>4}  "
                f"{f.metrics.get('mae', float('nan')):>10.4f}  "
                f"{_fmt(f.metrics.get('skill_vs_naive')):>8}  "
                f"{_fmt(f.metrics.get('directional_accuracy')):>8}"
            )
        return "\n".join(rows)


def _fmt(value) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def _take(inputs: PredictionFrame, idx: list[int]) -> PredictionFrame:
    return PredictionFrame(
        inputs.symbol,
        inputs.exchange,
        inputs.X.iloc[idx],
        inputs.target_dates.iloc[idx],
        inputs.features_hashes.iloc[idx],
    )


def _slice_training(frame: TrainingFrame, rows: range, *, before: pd.Timestamp) -> TrainingFrame:
    """Training slice for a fold, minus rows whose label leaks past ``before``."""
    idx = [i for i in rows if frame.target_available_at.iloc[i] <= before]
    return TrainingFrame(
        _take(frame.inputs, idx),
        frame.y.iloc[idx],
        frame.target_available_at.iloc[idx],
    )


def walk_forward(
    predictor_key: str,
    symbol: str,
    start: datetime,
    end: datetime,
    *,
    params: dict | None = None,
    scheme: str = EXPANDING,
    train_span: int = 250,
    test_span: int = 21,
    step: int = 21,
    gap: int = 1,
    provider_keys=DEFAULT_PROVIDERS,
    exchange: str = "PSX",
    exchange_timezone: str = "Asia/Karachi",
    allow_short: bool = False,
    long_threshold: float = 0.0,
    cost_bps: float = 0.0,
    initial_cash: float = 100_000.0,
) -> WalkForwardResult:
    params = dict(params or {})
    predictor_cls = get_predictor_class(predictor_key)  # fail fast on an unknown key

    frame = assemble_training_frame(
        symbol,
        start,
        end,
        exchange=exchange,
        exchange_timezone=exchange_timezone,
        provider_keys=provider_keys,
    )
    n = len(frame.inputs.X)
    folds = generate_folds(
        n, scheme=scheme, train_span=train_span, test_span=test_span, step=step, gap=gap
    )
    if not folds:
        raise ValueError(
            f"history too short for a single fold: {n} decision rows, need "
            f">= {train_span + gap + test_span}"
        )

    result = WalkForwardResult(
        predictor_key=predictor_key,
        params=params,
        symbol=symbol,
        exchange=exchange,
        scheme=scheme,
    )
    dec_index = frame.inputs.X.index
    dates = list(frame.inputs.target_dates)

    for fold in folds:
        first_test_decision = dec_index[fold.test.start]
        train_frame = _slice_training(frame, fold.train, before=first_test_decision)
        if train_frame.inputs.X.empty:
            result.skipped_folds.append(
                {"index": fold.index, "reason": "no training rows with an available label"}
            )
            continue

        predictor = predictor_cls(**params)
        try:
            predictor.fit(train_frame)
            test_inputs = _take(frame.inputs, list(fold.test))
            forecasts = predictor.predict_series(test_inputs)
        except Exception as exc:  # noqa: BLE001 - one bad fold must not kill the run
            result.skipped_folds.append(
                {"index": fold.index, "reason": f"{type(exc).__name__}: {exc}"}
            )
            continue

        rows = list(fold.test)
        predicted = [f.predicted_close for f in forecasts]
        actual = [float(v) for v in frame.y.iloc[rows]]
        anchor = [float(v) for v in test_inputs.X["price.close"]]
        for j, row in enumerate(rows):
            result.predictions.append(
                {
                    "fold": fold.index,
                    "as_of": dec_index[row].isoformat(),
                    "target_date": dates[row].isoformat(),
                    "anchor": anchor[j],
                    "predicted": predicted[j],
                    "actual": actual[j],
                }
            )
        result.folds.append(
            FoldReport(
                index=fold.index,
                train_start=dates[fold.train.start],
                train_end=dates[fold.train.stop - 1],
                test_start=dates[rows[0]],
                test_end=dates[rows[-1]],
                n_train=len(train_frame.inputs.X),
                n_test=len(rows),
                metrics=regression_scores(predicted, actual, anchor),
            )
        )

    if not result.folds:
        raise ValueError("every fold was skipped; see result.skipped_folds")

    pooled_pred = [p["predicted"] for p in result.predictions]
    pooled_actual = [p["actual"] for p in result.predictions]
    pooled_anchor = [p["anchor"] for p in result.predictions]
    pooled_dates = [date.fromisoformat(p["target_date"]) for p in result.predictions]

    result.metrics = regression_scores(pooled_pred, pooled_actual, pooled_anchor)
    result.naive_metrics = regression_scores(pooled_anchor, pooled_actual, pooled_anchor)
    result.trading = trading_translation(
        pooled_dates,
        pooled_pred,
        pooled_actual,
        pooled_anchor,
        allow_short=allow_short,
        long_threshold=long_threshold,
        cost_bps=cost_bps,
        initial_cash=initial_cash,
    )
    return result


def looks_leaky(result: WalkForwardResult, *, skill_ceiling: float = 0.98) -> bool:
    """Heuristic leak canary: an out-of-sample forecast should not near-perfectly
    reproduce the future. A predictor peeking at ``t+1`` posts an implausible
    pooled skill score or an essentially zero error."""
    skill = result.metrics.get("skill_vs_naive")
    mae = result.metrics.get("mae")
    r2 = result.metrics.get("r2")
    if mae is not None and mae < 1e-6:
        return True
    if skill is not None and skill > skill_ceiling:
        return True
    if r2 is not None and r2 > 0.999:
        return True
    return False
