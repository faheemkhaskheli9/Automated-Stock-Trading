"""Univariate statistical forecasts with training-only parameter estimation.

Replay supplies every new observed close in order. Each call starts from the
fitted history and updates states on its own prefix, without changing parameters
or retaining test observations between calls. Periods count observations, not days.
"""

import numpy as np

from .base import BasePredictor, PredictionFrame, PricePrediction, TrainingFrame
from .registry import register_predictor


class _StatisticalPredictor(BasePredictor):
    trainable = True

    def __init__(self, **params):
        super().__init__(**params)
        self._fitted = None

    def fit(self, history: TrainingFrame) -> None:
        self._fitted = None  # Failed refits must not leave a usable old model.
        if not isinstance(history, TrainingFrame):
            raise TypeError("fit requires a TrainingFrame")
        history.__post_init__()
        history.inputs.__post_init__()
        closes = history.inputs.X.get("price.close")
        if closes is None or len(closes) < 3:
            raise ValueError("Statistical predictors need at least three training rows")
        if not np.isfinite(closes).all() or (closes <= 0).any():
            raise ValueError("Training closes must be finite and positive")
        if not np.array_equal(history.y.iloc[:-1], closes.iloc[1:]) or not np.array_equal(
            history.target_available_at.iloc[:-1], history.inputs.X.index[1:]
        ):
            raise ValueError("Training rows must form a contiguous observation sequence")
        values = np.append(closes.to_numpy(dtype=float), float(history.y.iloc[-1]))
        result = self._model(values).fit(disp=False, maxiter=1000)
        if not result.mle_retvals.get("converged", False):
            raise ValueError("Statistical model fit did not converge")
        if not np.isfinite(result.params).all():
            raise ValueError("Statistical model fitted non-finite parameters")
        self._values = values
        self._parameters = np.array(result.params, copy=True)
        self.fitted_through = history.target_available_at.iloc[-1]
        self.instrument = (history.inputs.symbol, history.inputs.exchange)
        self._fitted = result

    def predict_series(self, frame: PredictionFrame) -> list[PricePrediction]:
        if not isinstance(frame, PredictionFrame):
            raise TypeError("predict_series accepts PredictionFrame, never training labels")
        frame.__post_init__()
        if frame.X.empty:
            return []
        if self._fitted is None:
            raise ValueError("Fit the statistical predictor before prediction")
        if (frame.symbol, frame.exchange) != self.instrument:
            raise ValueError("Fitted predictor belongs to a different instrument")
        if frame.X.index.min() < self.fitted_through:
            raise ValueError("Training labels extend beyond the prediction decision time")
        if frame.X.index.min() != self.fitted_through:
            raise ValueError(
                "Replay must start at fitted_through; refit with current history first"
            )
        values = self._values.copy()
        predictions = []
        for as_of, row in frame.X.iterrows():
            close = float(row["price.close"])
            if not np.isfinite(close) or close <= 0:
                raise ValueError("Prediction closes must be finite and positive")
            if as_of == self.fitted_through:
                if close != values[-1]:
                    raise ValueError("Prediction close conflicts with the final training label")
            else:
                values = np.append(values, close)
            result = self._model(values).smooth(self._parameters)
            predictions.append(
                PricePrediction(
                    target_date=frame.target_dates.loc[as_of],
                    predicted_close=float(np.asarray(result.forecast(1))[0]),
                    model_key=self.key,
                    features_hash=frame.features_hashes.loc[as_of],
                )
            )
        return predictions


@register_predictor("sarima")
class SarimaPredictor(_StatisticalPredictor):
    display_name = "SARIMA"

    def __init__(self, *, order=(1, 1, 0), seasonal_order=(0, 0, 0, 0), trend=None):
        super().__init__(order=order, seasonal_order=seasonal_order, trend=trend)

    def _model(self, values):
        from statsmodels.tsa.statespace.sarimax import SARIMAX

        return SARIMAX(values, **self.params)


@register_predictor("ets")
class EtsPredictor(_StatisticalPredictor):
    display_name = "Exponential smoothing (ETS)"

    def __init__(
        self, *, error="add", trend=None, damped_trend=False, seasonal=None, seasonal_periods=None
    ):
        super().__init__(
            error=error,
            trend=trend,
            damped_trend=damped_trend,
            seasonal=seasonal,
            seasonal_periods=seasonal_periods,
        )

    def _model(self, values):
        from statsmodels.tsa.exponential_smoothing.ets import ETSModel

        return ETSModel(values, **self.params)
