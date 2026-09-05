"""Forecast contract and input types.

Targets live outside PredictionFrame: predict_series never receives labels.
Daily bars are conservatively available at the following local midnight.
The caller supplies a verified next-session date for an operational forecast;
we do not invent an exchange holiday calendar or query future bars to find it.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime
from math import isfinite

import pandas as pd


@dataclass(frozen=True)
class PricePrediction:
    target_date: date
    predicted_close: float
    model_key: str
    features_hash: str
    lower: float | None = None
    upper: float | None = None
    confidence: float | None = None

    def __post_init__(self):
        if not isfinite(self.predicted_close) or self.predicted_close <= 0:
            raise ValueError("Predicted close must be finite and positive")
        if (self.lower is None) != (self.upper is None):
            raise ValueError("Prediction interval requires both bounds")
        if self.lower is not None and (
            not isfinite(self.lower)
            or not isfinite(self.upper)
            or not 0 < self.lower <= self.predicted_close <= self.upper
        ):
            raise ValueError("Invalid prediction interval")
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise ValueError("Confidence must be between zero and one")


@dataclass
class PredictionFrame:
    """Numeric X and aligned metadata, with NO actual future prices.

    X.index is an aware, increasing decision timestamp, not the bar's date
    label. Missing features remain NaN; an eventual imputer must fit only on
    training rows. One frame contains exactly one symbol/exchange.
    """

    symbol: str
    exchange: str
    X: pd.DataFrame
    target_dates: pd.Series
    features_hashes: pd.Series

    def __post_init__(self):
        index = self.X.index
        if not isinstance(index, pd.DatetimeIndex) or index.tz is None:
            raise ValueError("Decision index must be timezone-aware")
        if not index.is_unique or not index.is_monotonic_increasing:
            raise ValueError("Decision index must be unique and increasing")
        if not self.X.columns.is_unique:
            raise ValueError("Feature names must be unique")
        for series in (self.target_dates, self.features_hashes):
            if not series.index.equals(index):
                raise ValueError("Prediction metadata must align with X")


@dataclass
class TrainingFrame:
    inputs: PredictionFrame
    y: pd.Series
    target_available_at: pd.Series

    def __post_init__(self):
        for series in (self.y, self.target_available_at):
            if not series.index.equals(self.inputs.X.index):
                raise ValueError("Training labels must align with inputs")
        if not self.y.map(lambda v: isfinite(v) and v > 0).all():
            raise ValueError("Training closes must be finite and positive")
        if (
            not self.target_available_at.empty
            and not (self.target_available_at > self.inputs.X.index).all()
        ):
            raise ValueError("Targets must become available after their feature rows")


class BasePredictor(ABC):
    key = ""
    display_name = ""
    trainable = False

    def __init__(self, **params):
        self.params = params

    @abstractmethod
    def fit(self, history: TrainingFrame) -> None:
        """Fit only on a chronological training slice supplied by the caller."""

    @abstractmethod
    def predict_series(self, frame: PredictionFrame) -> list[PricePrediction]:
        """One forecast per input row, without reading DB data or labels."""

    def predict_next(
        self,
        symbol: str,
        as_of: datetime,
        *,
        target_date: date,
        exchange: str = "PSX",
        exchange_timezone: str = "Asia/Karachi",
    ) -> PricePrediction:
        from .features import assemble_prediction_frame

        frame = assemble_prediction_frame(
            symbol,
            as_of,
            target_date=target_date,
            exchange=exchange,
            exchange_timezone=exchange_timezone,
        )
        return self.predict_series(frame)[0]
