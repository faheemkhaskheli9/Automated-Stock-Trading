"""Transparent random-walk baselines; intervals/confidence are not fabricated."""

from .base import BasePredictor, PredictionFrame, PricePrediction, TrainingFrame
from .registry import register_predictor


@register_predictor("naive")
class NaiveClosePredictor(BasePredictor):
    display_name = "Last observed close"

    def fit(self, history: TrainingFrame) -> None:
        pass

    def _offset(self, frame):
        return 0.0

    def predict_series(self, frame: PredictionFrame) -> list[PricePrediction]:
        if not isinstance(frame, PredictionFrame):
            raise TypeError("predict_series accepts PredictionFrame, never training labels")
        if frame.X.empty:
            return []
        offset = self._offset(frame)
        return [
            PricePrediction(
                target_date=frame.target_dates.loc[as_of],
                predicted_close=float(row["price.close"]) + offset,
                model_key=self.key,
                features_hash=frame.features_hashes.loc[as_of],
            )
            for as_of, row in frame.X.iterrows()
        ]


@register_predictor("drift")
class DriftPredictor(NaiveClosePredictor):
    display_name = "Random walk with fitted drift"
    trainable = True

    def __init__(self, **params):
        super().__init__(**params)
        self.drift = None
        self.fitted_through = None
        self.instrument = None

    def fit(self, history: TrainingFrame) -> None:
        # Fit using one-step differences, including the final KNOWN target.
        # No full-series transform, future DB fetch, or inference-time refit.
        if history.inputs.X.empty:
            raise ValueError("Drift needs at least one labelled training observation")
        self.drift = float((history.y - history.inputs.X["price.close"]).mean())
        self.fitted_through = history.target_available_at.max()
        self.instrument = (history.inputs.symbol, history.inputs.exchange)

    def _offset(self, frame):
        if self.drift is None:
            raise ValueError("Fit the drift predictor before prediction")
        if (frame.symbol, frame.exchange) != self.instrument:
            raise ValueError("Fitted predictor belongs to a different instrument")
        if frame.X.index.min() < self.fitted_through:
            raise ValueError("Training labels extend beyond the prediction decision time")
        return self.drift
