"""Best-effort attribution for one prediction: which features drove it.

Feature attribution is estimator-specific. This module supports the common,
honest cases - linear coefficients and tree-based feature importances -
applied to the single row that was actually scored, and returns ``None``
for anything else (MLP, voting ensembles, multi-output/multistep wrappers,
the trivial baselines) rather than fabricating a reason.

Every notification about a prediction is expected to mention *something*
about why (see the project's notification-reason requirement); the caller is
responsible for saying "no attribution available for this estimator" when
this returns ``None``, instead of staying silent.
"""

from __future__ import annotations

import numpy as np
from sklearn.multioutput import MultiOutputRegressor

TOP_N = 3


def explain_prediction(pipeline, feature_names: list[str], X_row) -> dict | None:
    """``X_row``: the single-row DataFrame/2D array passed to
    ``pipeline.predict`` (same column order as ``feature_names``).

    Returns ``{"method": "linear_coefficients" | "feature_importance",
    "top_features": [{"feature", "value", "weight", "direction"}, ...]}`` or
    ``None`` when this estimator exposes no usable attribution.
    """
    model = pipeline.named_steps.get("model") if hasattr(pipeline, "named_steps") else None
    if model is None or isinstance(model, MultiOutputRegressor):
        return None

    raw_values = np.ravel(np.asarray(X_row))
    if len(raw_values) != len(feature_names):
        return None

    coef = getattr(model, "coef_", None)
    if coef is not None:
        coef = np.ravel(coef)
        if len(coef) != len(feature_names):
            return None
        pre = pipeline[:-1] if len(pipeline.steps) > 1 else None
        transformed = np.ravel(pre.transform(X_row)) if pre is not None else raw_values
        contributions = coef * transformed
        order = np.argsort(-np.abs(contributions))[:TOP_N]
        top = [
            {
                "feature": feature_names[i],
                "value": _clean(raw_values[i]),
                "weight": float(contributions[i]),
                "direction": "+" if contributions[i] >= 0 else "-",
            }
            for i in order
        ]
        return {"method": "linear_coefficients", "top_features": top}

    importances = getattr(model, "feature_importances_", None)
    if importances is not None:
        importances = np.ravel(importances)
        if len(importances) != len(feature_names):
            return None
        order = np.argsort(-importances)[:TOP_N]
        top = [
            {
                "feature": feature_names[i],
                "value": _clean(raw_values[i]),
                "weight": float(importances[i]),
                "direction": None,
            }
            for i in order
            if importances[i] > 0
        ]
        return {"method": "feature_importance", "top_features": top} if top else None

    return None


def _clean(value) -> float | None:
    value = float(value)
    return None if np.isnan(value) else value


def explanation_text(explanation: dict | None) -> str:
    """One human-readable line for a notification body."""
    if not explanation or not explanation.get("top_features"):
        return "no attribution available for this model"
    parts = []
    for feat in explanation["top_features"]:
        label = feat["feature"]
        value = f"={feat['value']:.3g}" if feat["value"] is not None else ""
        if feat["direction"] is not None:
            sign = "+" if feat["direction"] == "+" else "-"
            parts.append(f"{label}{value} ({sign}{abs(feat['weight']):.3g})")
        else:
            parts.append(f"{label}{value} (importance {feat['weight']:.2f})")
    return ", ".join(parts)
