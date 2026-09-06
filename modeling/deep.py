"""Optional PyTorch LSTM estimator.

torch is an optional extra (``requirements-ml.txt``). When it is not
installed this module imports cleanly, registers nothing, and
``LSTM_AVAILABLE`` is False - the estimators page then shows ``lstm`` as
unavailable (see ``registry.catalogue``) and selecting it is rejected by
``TradingModel.clean``.
"""

from __future__ import annotations

import numpy as np
from sklearn.base import BaseEstimator, RegressorMixin

from .estimators_base import TASK_REGRESSION, BaseEstimatorSpec
from .registry import register_estimator

try:  # pragma: no cover - exercised only where torch is installed
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

    class _TorchLSTM(BaseEstimator, RegressorMixin):
        """Sequence model over the last ``lookback`` engineered feature rows.

        Rows are assumed chronologically ordered (dataset.py sorts by
        decision timestamp). Every input row gets a prediction; the first
        ``lookback - 1`` rows are left-padded with a copy of the first row.
        """

        def __init__(self, lookback=20, hidden_size=32, layers=1, epochs=60, lr=1e-3):
            self.lookback = lookback
            self.hidden_size = hidden_size
            self.layers = layers
            self.epochs = epochs
            self.lr = lr

        def _windows(self, X):
            X = np.asarray(X, dtype=float)
            pad = np.repeat(X[:1], self.lookback - 1, axis=0)
            padded = np.vstack([pad, X])
            return np.stack([padded[i : i + self.lookback] for i in range(len(X))])

        def fit(self, X, y):
            self.n_features_in_ = np.asarray(X).shape[1]
            self._mean = np.nanmean(X, axis=0)
            self._std = np.nanstd(X, axis=0)
            self._std[self._std == 0] = 1.0
            windows = (self._windows(X) - self._mean) / self._std
            xt = torch.tensor(windows, dtype=torch.float32)
            yt = torch.tensor(np.asarray(y, dtype=float), dtype=torch.float32)
            torch.manual_seed(0)
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
            windows = (self._windows(X) - self._mean) / self._std
            self._net.eval()
            with torch.no_grad():
                return self._net(torch.tensor(windows, dtype=torch.float32)).numpy()

    @register_estimator("lstm")
    class LstmSpec(BaseEstimatorSpec):
        display_name = "LSTM (PyTorch)"
        task = TASK_REGRESSION
        needs_scaling = False  # the wrapper standardises internally
        multioutput = False
        available = True
        param_schema = {
            "lookback": (int, 20),
            "hidden_size": (int, 32),
            "layers": (int, 1),
            "epochs": (int, 60),
            "lr": (float, 1e-3),
        }

        @classmethod
        def make(cls, params: dict):
            return _TorchLSTM(**params)

else:

    @register_estimator("lstm")
    class LstmSpec(BaseEstimatorSpec):  # noqa: F811 - single definition per branch
        display_name = "LSTM (PyTorch)"
        task = TASK_REGRESSION
        needs_scaling = False
        multioutput = False
        available = False
        param_schema = {
            "lookback": (int, 20),
            "hidden_size": (int, 32),
            "layers": (int, 1),
            "epochs": (int, 60),
            "lr": (float, 1e-3),
        }

        @classmethod
        def make(cls, params: dict):
            raise RuntimeError(
                "The 'lstm' estimator needs the torch extra: pip install -r requirements-ml.txt"
            )
