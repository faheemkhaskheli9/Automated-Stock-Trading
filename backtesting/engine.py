"""Run a :class:`~backtesting.models.Backtest`, then translate the pooled
out-of-sample forecasts into a trade log and an equity curve.

Two fit modes:
* ``walk_forward`` (default) - retrain a fresh ``modeling.training`` pipeline
  every fold and score that fold's test window.
* ``frozen_artifact`` - load the model's already-trained joblib artifact
  (the latest, or a pinned ``training_run``) and score every session strictly
  after it was trained. One pseudo-fold; the fold-window config is ignored.

Every ``modeling`` target type is accepted. ``multistep`` models emit a
vector label/forecast; :func:`_final_step` collapses it to the last horizon
(predicted close ``steps`` sessions out vs the decision close) so the rest of
the pipeline - scoring, position sizing, the trade log - stays scalar.
``weekday_anchored`` models decide once a week and are scored like
``horizon_close``.

Design mirrors ``modeling.training.train_model``: this function **never
raises** - any failure is written to the :class:`BacktestRun` row
(``status="failed"`` + ``error``).

Leakage control:
* ``modeling.dataset.build_dataset`` already builds every feature point-in-
  time and keeps a row only once its label was observable.
* ``walk_forward``: per fold we additionally drop any training row whose label
  (``available_at``) was not known strictly before the fold's first test
  decision, and :func:`backtesting.walkforward.generate_folds` keeps the
  whole train block before the test block with a ``gap`` embargo.
* ``frozen_artifact``: only sessions dated strictly after the artifact's
  ``trained_at`` (local date) are scored - the artifact never trained on a
  label observable that late.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time

import joblib
import numpy as np
import pandas as pd
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from modeling.dataset import build_dataset
from modeling.estimators_base import TASK_CLASSIFICATION
from modeling.metrics import classification_metrics, regression_metrics
from modeling.training import build_pipeline
from strategies.backtesting.engine import BacktestResult
from strategies.backtesting.engine import Trade as StratTrade

from . import metrics as trade_mod
from .models import BacktestFold, BacktestPrediction, BacktestRun, BacktestTrade
from .walkforward import generate_folds

logger = logging.getLogger(__name__)

MIN_TRAIN_ROWS = 10


def _local_dates(index, tz):
    return np.array(index.tz_convert(tz).date)


def _final_step(values) -> np.ndarray:
    """Collapse a forecast/label array to one scalar per row.

    ``multistep`` models emit a vector (the next ``steps`` closes); the
    backtester trades a single decision, so it scores and sizes off the
    **last** horizon only - predicted close ``steps`` sessions out vs the
    decision close, exactly like ``horizon_close``. Single-output targets
    pass straight through.
    """
    arr = np.asarray(values, dtype=float)
    return arr[:, -1] if arr.ndim == 2 else arr.ravel()


def run_backtest(backtest, *, created_by=None) -> BacktestRun:
    run = BacktestRun.objects.create(backtest=backtest, created_by=created_by)
    try:
        _execute(backtest, run)
    except Exception as exc:  # noqa: BLE001 - recorded on the run, never propagated
        logger.exception("Backtest failed for backtest %s", backtest.pk)
        run.status = BacktestRun.Status.FAILED
        run.finished_at = timezone.now()
        run.error = f"{type(exc).__name__}: {exc}"
        run.save()
    return run


class _PredictionSink:
    """Row-level predictions plus the pooled arrays both scoring modes fill -
    keeps ``_score_frozen`` / ``_score_walk_forward`` signatures short."""

    def __init__(self):
        self.pred_rows: list[BacktestPrediction] = []
        # per-instrument ordered (as_of_date, anchor_close, position)
        self.series: dict[str, list[tuple]] = {}
        self.pooled_true: list[float] = []
        self.pooled_pred: list[float] = []
        self.pooled_anchor: list[float] = []


def _positions_and_metrics(bt, target_type, is_clf, raw, t_true, t_anchor, proba_up):
    positions = trade_mod.positions_from_forecast(
        target_type,
        raw,
        t_anchor,
        long_threshold=bt.long_threshold,
        allow_short=bt.allow_short,
        proba_up=proba_up,
    )
    if is_clf:
        fold_metrics = classification_metrics(t_true, np.round(raw), y_proba=proba_up)
    else:
        fold_metrics = regression_metrics(t_true, raw, anchor=t_anchor)
    return positions, fold_metrics


def _record_predictions(
    sink,
    *,
    run,
    ds,
    fold_index,
    test_idx,
    raw,
    t_true,
    t_anchor,
    positions,
    is_clf,
    inst_labels,
    sym_map,
    tdates,
    decision_dates,
):
    for k, row in enumerate(test_idx):
        symbol = inst_labels[row]
        pred_val = float(raw[k])
        actual = float(t_true[k])
        abs_err = (0.0 if round(pred_val) == actual else 1.0) if is_clf else abs(pred_val - actual)
        as_of_dt = ds.X.index[row].to_pydatetime()
        sink.pred_rows.append(
            BacktestPrediction(
                run=run,
                instrument=sym_map[symbol],
                fold_index=fold_index,
                as_of=as_of_dt,
                target_date=tdates[row],
                predicted_value=pred_val,
                actual_value=actual,
                abs_error=abs_err,
                position=int(positions[k]),
            )
        )
        sink.series.setdefault(symbol, []).append(
            (decision_dates[row], float(t_anchor[k]), int(positions[k]))
        )
    sink.pooled_true.extend(np.asarray(t_true).tolist())
    sink.pooled_pred.extend(np.asarray(raw).tolist())
    sink.pooled_anchor.extend(np.asarray(t_anchor).tolist())


def _score_walk_forward(
    *,
    bt,
    run,
    model,
    ds,
    tz,
    target_type,
    is_clf,
    decision_dates,
    avail,
    y_fit,
    y_scalar,
    anchor_arr,
    tdates,
    inst_labels,
    sym_map,
    sink,
    fold_rows,
) -> int:
    sessions = sorted(set(decision_dates.tolist()))
    folds = generate_folds(
        sessions,
        scheme=bt.scheme,
        train_span=bt.train_span,
        test_span=bt.test_span,
        step=bt.step,
        gap=bt.gap,
    )
    if not folds:
        raise ValueError(
            f"Only {len(sessions)} sessions of usable history - not enough for one "
            f"{bt.train_span}+{bt.gap}+{bt.test_span} fold. Import more data or shrink the spans."
        )

    used_folds = 0
    for fold in folds:
        test_mask = (decision_dates >= fold.test_start) & (decision_dates <= fold.test_end)
        if not test_mask.any():
            continue
        test_ts_min = ds.X.index[test_mask].min()
        train_mask = (
            (decision_dates >= fold.train_start)
            & (decision_dates <= fold.train_end)
            & (avail <= test_ts_min).to_numpy()
        )
        if train_mask.sum() < MIN_TRAIN_ROWS:
            continue

        train_idx = np.flatnonzero(train_mask)
        test_idx = np.flatnonzero(test_mask)

        pipeline = build_pipeline(model, ds)
        pipeline.fit(ds.X.iloc[train_idx], y_fit[train_idx])
        raw = _final_step(pipeline.predict(ds.X.iloc[test_idx]))
        proba_up = None
        if is_clf and hasattr(pipeline, "predict_proba"):
            proba_up = np.asarray(pipeline.predict_proba(ds.X.iloc[test_idx]))[:, 1]

        t_true = y_scalar[test_idx]
        t_anchor = anchor_arr[test_idx]
        positions, fold_metrics = _positions_and_metrics(
            bt, target_type, is_clf, raw, t_true, t_anchor, proba_up
        )

        fold_rows.append(
            BacktestFold(
                run=run,
                fold_index=fold.index,
                train_start=fold.train_start,
                train_end=fold.train_end,
                test_start=fold.test_start,
                test_end=fold.test_end,
                n_train=int(train_mask.sum()),
                n_test=int(test_mask.sum()),
                metrics=fold_metrics,
            )
        )
        _record_predictions(
            sink,
            run=run,
            ds=ds,
            fold_index=fold.index,
            test_idx=test_idx,
            raw=raw,
            t_true=t_true,
            t_anchor=t_anchor,
            positions=positions,
            is_clf=is_clf,
            inst_labels=inst_labels,
            sym_map=sym_map,
            tdates=tdates,
            decision_dates=decision_dates,
        )
        used_folds += 1

    return used_folds


def _score_frozen(
    *,
    bt,
    run,
    model,
    ds,
    tz,
    target_type,
    is_clf,
    decision_dates,
    avail,
    y_fit,
    y_scalar,
    anchor_arr,
    tdates,
    inst_labels,
    sym_map,
    sink,
    fold_rows,
) -> int:
    # ``tz`` and ``avail`` are accepted for a uniform scorer signature;
    # frozen mode gates on the artifact's trained-at date, not per-fold
    # availability, and both scorers are called with the same kwargs.
    artifact_path = bt.artifact_path
    if not artifact_path:
        raise ValueError(
            "Frozen-artifact mode needs a trained model - train it first, or pin a "
            "training run with a saved artifact"
        )
    payload = joblib.load(artifact_path)
    if list(payload.get("feature_names") or []) != list(ds.feature_names):
        raise ValueError(
            "The model's feature spec changed since this artifact was trained - retrain it "
            "or pin the matching training run"
        )
    if payload.get("target_spec") not in (None, model.target_spec):
        raise ValueError(
            "The model's target spec changed since this artifact was trained - retrain it"
        )
    if "multioutput" in payload and bool(payload["multioutput"]) != bool(
        getattr(ds, "multioutput", False)
    ):
        raise ValueError(
            "The model's target shape (single- vs multi-output) changed since this artifact "
            "was trained - retrain it"
        )

    trained_at = pd.Timestamp(payload["trained_at"])
    if trained_at.tzinfo is None:
        trained_at = trained_at.tz_localize("UTC")
    trained_date = trained_at.tz_convert(tz).date()

    # Out-of-sample boundary: the artifact could only have trained on labels
    # observable by the *earlier* of (when training ran) and (its configured
    # ``train_end``). Sessions strictly after that are genuine hold-out. Older
    # artifacts predate the ``train_end`` key - fall back to the model's field.
    payload_end = payload.get("train_end")
    model_end = model.train_end.isoformat() if model.train_end else None
    configured_end = payload_end or model_end
    oos_after = trained_date
    if configured_end:
        oos_after = min(trained_date, date.fromisoformat(configured_end))

    test_mask = decision_dates > oos_after
    n_test = int(test_mask.sum())
    if n_test < MIN_TRAIN_ROWS:
        raise ValueError(
            f"Only {n_test} sessions of history after the artifact's training cut-off "
            f"({oos_after.isoformat()}) - not enough to score. Set the model's train_end to "
            "an earlier date and retrain, or import more recent price data."
        )
    test_idx = np.flatnonzero(test_mask)

    pipeline = payload["pipeline"]
    raw = _final_step(pipeline.predict(ds.X.iloc[test_idx]))
    proba_up = None
    if is_clf and hasattr(pipeline, "predict_proba"):
        proba_up = np.asarray(pipeline.predict_proba(ds.X.iloc[test_idx]))[:, 1]

    t_true = y_scalar[test_idx]
    t_anchor = anchor_arr[test_idx]
    positions, fold_metrics = _positions_and_metrics(
        bt, target_type, is_clf, raw, t_true, t_anchor, proba_up
    )

    test_dates = decision_dates[test_idx]
    fold_rows.append(
        BacktestFold(
            run=run,
            fold_index=0,
            train_start=model.train_start or oos_after,
            train_end=oos_after,
            test_start=min(test_dates),
            test_end=max(test_dates),
            n_train=0,
            n_test=n_test,
            metrics=fold_metrics,
        )
    )
    _record_predictions(
        sink,
        run=run,
        ds=ds,
        fold_index=0,
        test_idx=test_idx,
        raw=raw,
        t_true=t_true,
        t_anchor=t_anchor,
        positions=positions,
        is_clf=is_clf,
        inst_labels=inst_labels,
        sym_map=sym_map,
        tdates=tdates,
        decision_dates=decision_dates,
    )
    return 1


def _execute(bt, run) -> None:
    tz = settings.TIME_ZONE
    model = bt.model
    target_type = bt.target_type

    # ``build_dataset`` falls back to ``model.train_end`` when no end is given.
    # For frozen-artifact scoring that would cap the evaluation window at the
    # training cut-off, leaving nothing out-of-sample to score - the backtest
    # must reach forward to today (or its own explicit ``end``).
    ds_end = bt.end
    if bt.fit_mode == bt.FitMode.FROZEN_ARTIFACT and ds_end is None:
        ds_end = timezone.localdate()
    ds = build_dataset(model, start=bt.start, end=ds_end, for_training=True)

    # ``multistep`` models emit a vector label; ``y_fit`` keeps the full shape
    # for the estimator, ``y_scalar`` is the last horizon that scoring, position
    # sizing and the trade log all key off (see ``_final_step``).
    is_multi = bool(getattr(ds, "multioutput", False))
    y_fit = np.asarray(ds.y, dtype=float) if is_multi else np.asarray(ds.y, dtype=float).ravel()
    y_scalar = _final_step(ds.y)

    decision_dates = _local_dates(ds.X.index, tz)
    is_clf = ds.task == TASK_CLASSIFICATION
    sym_map = {i.symbol: i for i in model.instruments.all()}

    sink = _PredictionSink()
    fold_rows: list[BacktestFold] = []
    scorer = _score_frozen if bt.fit_mode == bt.FitMode.FROZEN_ARTIFACT else _score_walk_forward
    used_folds = scorer(
        bt=bt,
        run=run,
        model=model,
        ds=ds,
        tz=tz,
        target_type=target_type,
        is_clf=is_clf,
        decision_dates=decision_dates,
        avail=ds.available_at,
        y_fit=y_fit,
        y_scalar=y_scalar,
        anchor_arr=np.asarray(ds.anchor, dtype=float),
        tdates=list(ds.target_dates),
        inst_labels=np.asarray(ds.instrument_labels),
        sym_map=sym_map,
        sink=sink,
        fold_rows=fold_rows,
    )

    if used_folds == 0:
        raise ValueError("No fold had both enough training rows and any test rows")

    pooled_true = sink.pooled_true
    pooled_pred = sink.pooled_pred
    pooled_anchor = sink.pooled_anchor
    pred_rows = sink.pred_rows
    series = sink.series

    # ---- trade / equity simulation ------------------------------------
    n_inst = max(len(series), 1)
    per_alloc = bt.initial_cash / n_inst
    curves: list[list[tuple]] = []
    trade_rows: list[BacktestTrade] = []
    strat_trades: list[StratTrade] = []
    for symbol, points in series.items():
        points.sort(key=lambda p: p[0])
        deduped: list[tuple] = []
        seen: set = set()
        for d, close, pos in points:
            if d in seen:
                continue
            seen.add(d)
            deduped.append((d, close, pos))
        dates = [d for d, _, _ in deduped]
        closes = np.array([c for _, c, _ in deduped], dtype=float)
        positions = np.array([p for _, _, p in deduped], dtype=int)
        curve, trades = trade_mod.simulate_instrument(
            dates,
            closes,
            positions,
            initial_cash=per_alloc,
            commission_bps=bt.commission_bps,
            slippage_bps=bt.slippage_bps,
        )
        curves.append(curve)
        for t in trades:
            trade_rows.append(
                BacktestTrade(
                    run=run,
                    instrument=sym_map[symbol],
                    direction=t["direction"],
                    entry_date=t["entry_date"],
                    exit_date=t["exit_date"],
                    entry_price=t["entry_price"],
                    exit_price=t["exit_price"],
                    shares=t["shares"],
                    fees=t["fees"],
                    pnl=t["pnl"],
                    return_pct=t["return_pct"],
                )
            )
            strat_trades.append(
                StratTrade(
                    entry_time=datetime.combine(t["entry_date"], time.min),
                    entry_price=t["entry_price"],
                    exit_time=datetime.combine(t["exit_date"], time.min),
                    exit_price=t["exit_price"],
                    shares=int(round(t["shares"])) or (1 if t["direction"] > 0 else -1),
                    fees=t["fees"],
                )
            )

    combined = trade_mod.combine_equity_curves(curves, bt.initial_cash)
    equity_curve = [[d.isoformat(), round(v, 2)] for d, v in combined]
    eq_dt = [(datetime.combine(d, time.min), v) for d, v in combined]
    result = BacktestResult(
        initial_cash=bt.initial_cash,
        final_equity=eq_dt[-1][1] if eq_dt else bt.initial_cash,
        equity_curve=eq_dt,
        trades=strat_trades,
    )

    if is_clf:
        accuracy = classification_metrics(np.array(pooled_true), np.round(pooled_pred))
    else:
        accuracy = regression_metrics(
            np.array(pooled_true), np.array(pooled_pred), anchor=np.array(pooled_anchor)
        )

    trading = {
        "total_return": result.total_return,
        "cagr": result.cagr,
        "max_drawdown": result.max_drawdown,
        "sharpe": result.sharpe,
        "win_rate": result.win_rate,
        "num_trades": result.num_trades,
        "final_equity": round(result.final_equity, 2),
    }

    with transaction.atomic():
        BacktestFold.objects.bulk_create(fold_rows)
        BacktestPrediction.objects.bulk_create(pred_rows)
        BacktestTrade.objects.bulk_create(trade_rows)
        run.status = BacktestRun.Status.SUCCESS
        run.finished_at = timezone.now()
        run.n_folds = used_folds
        run.n_predictions = len(pred_rows)
        run.n_trades = len(trade_rows)
        run.metrics = {
            "accuracy": accuracy,
            "trading": trading,
            "scheme": bt.scheme,
            "fit_mode": bt.fit_mode,
            "target": target_type,
            "multioutput": bool(getattr(ds, "multioutput", False)),
            "instruments": sorted(series),
        }
        run.equity_curve = equity_curve
        run.save()
