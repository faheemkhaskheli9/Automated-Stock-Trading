"""Regularised linear predictors over the full point-in-time feature frame.

Unlike the univariate statistical predictors, these consume every assembled
feature (price lags/returns plus any research bundles). The target is the
next-session simple return ``y / close - 1``; the forecast is rebuilt as
``close * (1 + predicted_return)`` so a near-zero prediction reproduces the
naive last-close baseline.

The fit/predict/leakage-guard contract lives in
:class:`forecasting._frame_model.FrameModelPredictor`; this module only adds
the imputer+scaler pipeline stage and the concrete linear estimators.
"""

from ._frame_model import _MIN_TRAINING_ROWS, FrameModelPredictor  # noqa: F401
from .registry import register_predictor


class _LinearPredictor(FrameModelPredictor):
    def _build_pipeline(self):
        from sklearn.impute import SimpleImputer
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler

        # keep_empty_features: an all-NaN warmup column must survive imputation
        # so train and predict never disagree on column count.
        return Pipeline(
            [
                ("impute", SimpleImputer(strategy="median", keep_empty_features=True)),
                ("scale", StandardScaler()),
                ("model", self._estimator()),
            ]
        )


@register_predictor("ridge")
class RidgePredictor(_LinearPredictor):
    display_name = "Ridge regression on point-in-time features"

    def __init__(self, *, alpha=1.0):
        super().__init__(alpha=alpha)

    def _estimator(self):
        from sklearn.linear_model import Ridge

        return Ridge(alpha=self.params["alpha"])


@register_predictor("elasticnet")
class ElasticNetPredictor(_LinearPredictor):
    display_name = "ElasticNet regression on point-in-time features"

    def __init__(self, *, alpha=0.1, l1_ratio=0.5):
        super().__init__(alpha=alpha, l1_ratio=l1_ratio)

    def _estimator(self):
        from sklearn.linear_model import ElasticNet

        return ElasticNet(
            alpha=self.params["alpha"],
            l1_ratio=self.params["l1_ratio"],
            max_iter=10_000,
        )
