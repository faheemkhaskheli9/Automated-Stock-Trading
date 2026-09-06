"""Scoring for a fitted model on a train / holdout slice.

All functions return plain ``dict[str, float]`` (JSON-serialisable) so the
result can be stored on ``ModelTrainingRun.metrics`` and rendered directly.
"""

from __future__ import annotations

import numpy as np
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    precision_score,
    r2_score,
    recall_score,
    roc_auc_score,
)


def _finite_mask(*arrays):
    mask = np.ones(len(arrays[0]), dtype=bool)
    for arr in arrays:
        a = np.asarray(arr, dtype=float)
        mask &= np.isfinite(a) if a.ndim == 1 else np.isfinite(a).all(axis=1)
    return mask


def regression_metrics(y_true, y_pred, *, anchor=None) -> dict:
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    arrays = [y_true, y_pred] + ([np.asarray(anchor, dtype=float)] if anchor is not None else [])
    mask = _finite_mask(*arrays)
    y_true, y_pred = y_true[mask], y_pred[mask]
    if not len(y_true):
        return {}

    err = y_pred - y_true
    flat_true = y_true.reshape(-1)
    flat_err = err.reshape(-1)
    nonzero = flat_true != 0
    out = {
        "n": int(len(y_true)),
        "mae": float(np.mean(np.abs(flat_err))),
        "rmse": float(np.sqrt(np.mean(flat_err**2))),
        "mape": (
            float(np.mean(np.abs(flat_err[nonzero] / flat_true[nonzero])) * 100)
            if nonzero.any()
            else None
        ),
        "r2": float(r2_score(y_true, y_pred)),
    }
    if anchor is not None and y_true.ndim == 1:
        anchor = np.asarray(anchor, dtype=float)[mask]
        naive_mae = float(np.mean(np.abs(anchor - y_true)))
        out["directional_accuracy"] = float(
            np.mean(np.sign(y_pred - anchor) == np.sign(y_true - anchor))
        )
        out["skill_vs_naive"] = float(1 - out["mae"] / naive_mae) if naive_mae else None
        out["naive_mae"] = naive_mae
    return out


def classification_metrics(y_true, y_pred, *, y_proba=None) -> dict:
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    mask = _finite_mask(y_true, y_pred)
    y_true, y_pred = y_true[mask], y_pred[mask]
    if not len(y_true):
        return {}
    out = {
        "n": int(len(y_true)),
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
        "positive_rate": float(np.mean(y_true)),
    }
    if y_proba is not None:
        proba = np.asarray(y_proba, dtype=float)[mask]
        if len(np.unique(y_true)) == 2:
            out["roc_auc"] = float(roc_auc_score(y_true, proba))
    return out
