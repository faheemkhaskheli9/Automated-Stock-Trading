"""Gradient-boosted trees over the full point-in-time feature frame.

Mirrors :mod:`forecasting.linear` exactly -- same next-session simple-return
target, same ``close * (1 + predicted_return)`` reconstruction, and the same
instrument / label-boundary / feature-schema guards from
:class:`forecasting._frame_model.FrameModelPredictor`. The only difference is
the estimator: :class:`~sklearn.ensemble.HistGradientBoostingRegressor`
consumes the raw feature matrix directly (it handles NaNs natively), so no
imputation or scaling stage is prepended -- the default pipeline is used.
"""

from ._frame_model import FrameModelPredictor
from .registry import register_predictor


@register_predictor("gradient_boosting")
class GradientBoostingPredictor(FrameModelPredictor):
    display_name = "Histogram gradient-boosted trees on point-in-time features"

    def __init__(
        self,
        *,
        learning_rate=0.1,
        max_iter=200,
        max_depth=None,
        min_samples_leaf=20,
        l2_regularization=0.0,
        random_state=0,
    ):
        super().__init__(
            learning_rate=learning_rate,
            max_iter=max_iter,
            max_depth=max_depth,
            min_samples_leaf=min_samples_leaf,
            l2_regularization=l2_regularization,
            random_state=random_state,
        )

    def _estimator(self):
        from sklearn.ensemble import HistGradientBoostingRegressor

        params = self.params
        return HistGradientBoostingRegressor(
            learning_rate=params["learning_rate"],
            max_iter=params["max_iter"],
            max_depth=params["max_depth"],
            min_samples_leaf=params["min_samples_leaf"],
            l2_regularization=params["l2_regularization"],
            random_state=params["random_state"],
        )
