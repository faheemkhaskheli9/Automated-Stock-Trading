"""Leakage-safe walk-forward evaluation for the strict `forecasting` predictors.

This is the `forecasting.BasePredictor` counterpart to the standalone
`backtesting` app (which evaluates `modeling.TradingModel`). It refits a fresh
predictor per fold over `forecasting.features.assemble_training_frame`, never
crossing the train/test boundary with a fitted object or a label.
"""

from .engine import WalkForwardResult, looks_leaky, walk_forward
from .walkforward import Fold, generate_folds

__all__ = [
    "Fold",
    "generate_folds",
    "WalkForwardResult",
    "walk_forward",
    "looks_leaky",
]
