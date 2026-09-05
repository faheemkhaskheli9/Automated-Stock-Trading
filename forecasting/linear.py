"""Regularised linear predictors over the full point-in-time feature frame.

Unlike the univariate statistical predictors, these consume every assembled
feature (price lags/returns plus any research bundles). The target is the
next-session simple return ``y / close - 1``; the forecast is rebuilt as
``close * (1 + predicted_return)`` so a near-zero prediction reproduces the
naive last-close baseline.

Leakage guards mirror ``naive.DriftPredictor``: the scaler/imputer are fit
only inside :meth:`fit` (never across a fold boundary), the fitted feature
schema is pinned, and inference is refused for a different instrument or for
rows whose labels were still inside the training window.
"""

import numpy as np

from .base import BasePredictor, PredictionFrame, PricePrediction, TrainingFrame
from .registry import register_predictor

_MIN_TRAINING_ROWS = 5


class _LinearPredictor(BasePredictor):
    trainable = True

    def __init__(self, **params):
        super().__init__(**params)
        self._pipeline = None
        self._feature_names = None
        self.fitted_through = None
        self.instrument = None

    def _estimator(self):
        raise NotImplementedError

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

    def fit(self, history: TrainingFrame) -> None:
        self._pipeline = None  # A failed refit must not leave a usable old model.
        if not isinstance(history, TrainingFrame):
            raise TypeError("fit requires a TrainingFrame")
        history.__post_init__()
        history.inputs.__post_init__()
        features = history.inputs.X
        closes = features.get("price.close")
        if closes is None:
            raise ValueError("Training frame must include a 'price.close' feature")
        if len(features) < _MIN_TRAINING_ROWS:
            raise ValueError(f"Linear predictors need at least {_MIN_TRAINING_ROWS} training rows")
        closes = closes.to_numpy(dtype=float)
        if not np.isfinite(closes).all() or (closes <= 0).any():
            raise ValueError("Training closes must be finite and positive")
        returns = history.y.to_numpy(dtype=float) / closes - 1.0
        if not np.isfinite(returns).all():
            raise ValueError("Training returns are not all finite")
        pipeline = self._build_pipeline()
        pipeline.fit(features, returns)
        self._feature_names = list(features.columns)
        self._pipeline = pipeline
        self.fitted_through = history.target_available_at.max()
        self.instrument = (history.inputs.symbol, history.inputs.exchange)

    def predict_series(self, frame: PredictionFrame) -> list[PricePrediction]:
        if not isinstance(frame, PredictionFrame):
            raise TypeError("predict_series accepts PredictionFrame, never training labels")
        frame.__post_init__()
        if frame.X.empty:
            return []
        if self._pipeline is None:
            raise ValueError("Fit the linear predictor before prediction")
        if (frame.symbol, frame.exchange) != self.instrument:
            raise ValueError("Fitted predictor belongs to a different instrument")
        if frame.X.index.min() < self.fitted_through:
            raise ValueError("Training labels extend beyond the prediction decision time")
        missing = [name for name in self._feature_names if name not in frame.X.columns]
        extra = [name for name in frame.X.columns if name not in self._feature_names]
        if missing or extra:
            raise ValueError(
                "Prediction features do not match the training schema; "
                f"missing={missing} extra={extra}"
            )
        features = frame.X[self._feature_names]
        closes = features["price.close"].to_numpy(dtype=float)
        if not np.isfinite(closes).all() or (closes <= 0).any():
            raise ValueError("Prediction closes must be finite and positive")
        predicted_returns = np.asarray(self._pipeline.predict(features), dtype=float)
        predictions = []
        for as_of, close_now, predicted_return in zip(features.index, closes, predicted_returns):
            predictions.append(
                PricePrediction(
                    target_date=frame.target_dates.loc[as_of],
                    predicted_close=float(close_now * (1.0 + predicted_return)),
                    model_key=self.key,
                    features_hash=frame.features_hashes.loc[as_of],
                )
            )
        return predictions


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
