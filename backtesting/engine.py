"""Run a :class:`~backtesting.models.Backtest`: walk-forward retrain + score,
then translate the pooled out-of-sample forecasts into a trade log and an
equity curve.

Design mirrors ``modeling.training.train_model``: this function **never
raises** - any failure is written to the :class:`BacktestRun` row
(``status="failed"`` + ``error``).

Leakage control:
* ``modeling.dataset.build_dataset`` already builds every feature point-in-
  time and keeps a row only once its label was observable.
* Per fold we additionally drop any training row whose label
  (``available_at``) was not known strictly before the fold's first test
  decision, and :func:`backtesting.walkforward.generate_folds` keeps the
  whole train block before the test block with a ``gap`` embargo.
"""

from __future__ import annotations

import logging
from datetime import datetime, time

import numpy as np
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


def _execute(bt, run) -> None:
    tz = settings.TIME_ZONE
    model = bt.model
    target_type = bt.target_type

    ds = build_dataset(model, start=bt.start, end=bt.end, for_training=True)
    if getattr(ds, "multioutput", False):
        raise ValueError("Multi-output targets are not backtestable in v1")

    decision_dates = _local_dates(ds.X.index, tz)
    avail = ds.available_at
    y_arr = np.asarray(ds.y, dtype=float).ravel()
    anchor_arr = np.asarray(ds.anchor, dtype=float)
    tdates = list(ds.target_dates)
    inst_labels = np.asarray(ds.instrument_labels)
    sym_map = {i.symbol: i for i in model.instruments.all()}

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

    is_clf = ds.task == TASK_CLASSIFICATION
    pooled_true: list[float] = []
    pooled_pred: list[float] = []
    pooled_anchor: list[float] = []
    pred_rows: list[BacktestPrediction] = []
    fold_rows: list[BacktestFold] = []
    # per-instrument ordered (as_of_date, anchor_close, position)
    series: dict[str, list[tuple]] = {}
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
        pipeline.fit(ds.X.iloc[train_idx], y_arr[train_idx])
        raw = np.asarray(pipeline.predict(ds.X.iloc[test_idx]), dtype=float).ravel()
        proba_up = None
        if is_clf and hasattr(pipeline, "predict_proba"):
            proba_up = np.asarray(pipeline.predict_proba(ds.X.iloc[test_idx]))[:, 1]

        t_true = y_arr[test_idx]
        t_anchor = anchor_arr[test_idx]
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

        for k, row in enumerate(test_idx):
            symbol = inst_labels[row]
            pred_val = float(raw[k])
            actual = float(t_true[k])
            abs_err = (
                (0.0 if round(pred_val) == actual else 1.0) if is_clf else abs(pred_val - actual)
            )
            as_of_dt = ds.X.index[row].to_pydatetime()
            pred_rows.append(
                BacktestPrediction(
                    run=run,
                    instrument=sym_map[symbol],
                    fold_index=fold.index,
                    as_of=as_of_dt,
                    target_date=tdates[row],
                    predicted_value=pred_val,
                    actual_value=actual,
                    abs_error=abs_err,
                    position=int(positions[k]),
                )
            )
            series.setdefault(symbol, []).append(
                (decision_dates[row], float(t_anchor[k]), int(positions[k]))
            )

        pooled_true.extend(t_true.tolist())
        pooled_pred.extend(raw.tolist())
        pooled_anchor.extend(t_anchor.tolist())
        used_folds += 1

    if used_folds == 0:
        raise ValueError("No fold had both enough training rows and any test rows")

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
            "instruments": sorted(series),
        }
        run.equity_curve = equity_curve
        run.save()
