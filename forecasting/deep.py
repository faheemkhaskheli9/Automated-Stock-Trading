"""Optional PyTorch LSTM predictor over the full point-in-time feature frame.

``torch`` is an optional extra (``requirements-ml.txt``). When it is not
installed this module imports cleanly, ``LSTM_AVAILABLE`` is ``False`` and
**nothing is registered** -- ``registered_keys()`` simply will not contain
``"lstm"`` and ``get_predictor_class("lstm")`` raises. Install the extra only
where the LSTM is actually wanted.

When available, ``LstmPredictor`` shares the fit/predict/leakage-guard contract
of :class:`forecasting._frame_model.FrameModelPredictor` with the linear and
tree predictors: the same next-session simple-return target, the same
``close * (1 + predicted_return)`` reconstruction, and the same instrument /
label-boundary / feature-schema guards. The only additions are a median
imputer stage (the network cannot consume NaNs) and the sequence model itself.

Sequence caveat: the predictor keeps no training tail, so at inference the
first ``lookback - 1`` rows of a frame are left-padded with a copy of that
frame's first row rather than with real prior history. Forecasts stay causal
(row ``i`` depends only on rows ``<= i`` within the frame), so a single-row
operational ``predict_next`` call degenerates to a window of copies. This
mirrors ``modeling.deep`` and is adequate for a v1.
"""

from __future__ import annotations

import numpy as np
from sklearn.base import BaseEstimator, RegressorMixin

from ._frame_model import FrameModelPredictor
from .registry import register_predictor

try:  # pragma: no cover - exercised only where the torch extra is installed
    import torch
    from torch import nn

    LSTM_AVAILABLE = True
except ImportError:  # pragma: no cover - the default in this repo's env
    torch = None
    nn = None
    LSTM_AVAILABLE = False


if LSTM_AVAILABLE:  # pragma: no cover - needs the torch extra

    class _LSTMNet(nn.Module):
        def __init__(self, n_features: int, hidden_size: int, layers: int):
            super().__init__()
            self.lstm = nn.LSTM(
                input_size=n_features,
                hidden_size=hidden_size,
                num_layers=layers,
                batch_first=True,
            )
            self.head = nn.Linear(hidden_size, 1)

        def forward(self, x):
            out, _ = self.lstm(x)
            return self.head(out[:, -1, :]).squeeze(-1)

    class _TorchLSTMRegressor(BaseEstimator, RegressorMixin):
        """sklearn-compatible sequence regressor over trailing feature rows.

        Rows are assumed chronologically ordered (the frame's decision index
        is increasing). Every input row gets one prediction; the first
        ``lookback - 1`` rows are left-padded with a copy of the first row.
        Features are standardised inside the wrapper, so the pipeline needs
        no separate scaler.
        """

        def __init__(
            self,
            lookback=20,
            hidden_size=32,
            layers=1,
            epochs=60,
            lr=1e-3,
            random_state=0,
        ):
            self.lookback = lookback
            self.hidden_size = hidden_size
            self.layers = layers
            self.epochs = epochs
            self.lr = lr
            self.random_state = random_state

        def _windows(self, X):
            X = np.asarray(X, dtype=float)
            pad = np.repeat(X[:1], self.lookback - 1, axis=0)
            padded = np.vstack([pad, X])
            return np.stack([padded[i : i + self.lookback] for i in range(len(X))])

        def fit(self, X, y):
            self.n_features_in_ = np.asarray(X, dtype=float).shape[1]
            self._mean = np.nanmean(X, axis=0)
            self._std = np.nanstd(X, axis=0)
            self._std[~np.isfinite(self._std) | (self._std == 0)] = 1.0
            windows = np.nan_to_num((self._windows(X) - self._mean) / self._std)
            xt = torch.tensor(windows, dtype=torch.float32)
            yt = torch.tensor(np.asarray(y, dtype=float), dtype=torch.float32)
            torch.manual_seed(self.random_state)
            self._net = _LSTMNet(self.n_features_in_, self.hidden_size, self.layers)
            opt = torch.optim.Adam(self._net.parameters(), lr=self.lr)
            loss_fn = nn.MSELoss()
            self._net.train()
            for _ in range(self.epochs):
                opt.zero_grad()
                loss_fn(self._net(xt), yt).backward()
                opt.step()
            return self

        def predict(self, X):
            windows = np.nan_to_num((self._windows(X) - self._mean) / self._std)
            self._net.eval()
            with torch.no_grad():
                return self._net(torch.tensor(windows, dtype=torch.float32)).numpy()

    @register_predictor("lstm")
    class LstmPredictor(FrameModelPredictor):
        display_name = "PyTorch LSTM on point-in-time features"

        def __init__(
            self,
            *,
            lookback=20,
            hidden_size=32,
            layers=1,
            epochs=60,
            lr=1e-3,
            random_state=0,
        ):
            super().__init__(
                lookback=lookback,
                hidden_size=hidden_size,
                layers=layers,
                epochs=epochs,
                lr=lr,
                random_state=random_state,
            )

        def _build_pipeline(self):
            from sklearn.impute import SimpleImputer
            from sklearn.pipeline import Pipeline

            # The network standardises internally, but it cannot see NaNs; an
            # all-NaN warmup column must survive (keep_empty_features) so the
            # fitted feature count matches at prediction time.
            return Pipeline(
                [
                    ("impute", SimpleImputer(strategy="median", keep_empty_features=True)),
                    ("model", self._estimator()),
                ]
            )

        def _estimator(self):
            return _TorchLSTMRegressor(**self.params)
