"""PyTorch models with a scikit-learn face (fit / predict / predict_proba / score_samples).

* ``mlp``  – a deep feed-forward network (batch norm, dropout);
* ``lstm`` – a recurrent network reading the past dates in order;
* ``tcn``  – a temporal convolutional network (1-D convolutions over the dates);
* ``TorchAutoencoder`` – rebuilds normal pixels; its rebuild error scores anomalies.

Sequence models read the first ``sequence_length`` feature columns as the time series
(oldest first) and the remaining columns as static features joined after the sequence
part. Training stops early when a held-out tenth stops improving. Runs on the CPU, or on a
CUDA GPU when the service sets ``device="cuda"`` (and PyTorch can see one).
"""

from __future__ import annotations

import os

import numpy as np

MAX_EPOCHS = 80
PATIENCE = 8
BATCH = 512


def _torch():
    import torch

    torch.set_num_threads(max(1, os.cpu_count() or 1))
    return torch


def _device(torch, wanted: str = "cpu"):
    return torch.device("cuda" if wanted == "cuda" and torch.cuda.is_available() else "cpu")


def _network(torch, kind: str, n_in: int, n_out: int, sequence_length: int):
    nn = torch.nn

    if kind in ("lstm", "tcn") and sequence_length < 2:
        raise ValueError("needs at least two past dates per pixel (set 'past dates used' to 2 or more)")
    if kind == "mlp":
        return nn.Sequential(
            nn.Linear(n_in, 128), nn.BatchNorm1d(128), nn.ReLU(), nn.Dropout(0.1),
            nn.Linear(128, 64), nn.BatchNorm1d(64), nn.ReLU(), nn.Dropout(0.1),
            nn.Linear(64, 32), nn.ReLU(), nn.Linear(32, n_out))

    n_static = n_in - sequence_length

    class Sequence(nn.Module):
        def __init__(self):
            super().__init__()
            if kind == "lstm":
                self.body = nn.LSTM(input_size=1, hidden_size=48, num_layers=2, batch_first=True, dropout=0.1)
                width = 48
            else:   # tcn: dilated causal convolutions
                self.body = nn.Sequential(
                    nn.Conv1d(1, 32, kernel_size=2, padding=1), nn.ReLU(),
                    nn.Conv1d(32, 32, kernel_size=2, padding=2, dilation=2), nn.ReLU(),
                    nn.AdaptiveMaxPool1d(1))
                width = 32
            self.head = nn.Sequential(nn.Linear(width + n_static, 64), nn.ReLU(), nn.Linear(64, n_out))

        def forward(self, x):
            seq = x[:, :sequence_length].unsqueeze(-1)            # (batch, time, 1)
            static = x[:, sequence_length:]
            if kind == "lstm":
                out, _ = self.body(seq)
                summary = out[:, -1]
            else:
                summary = self.body(seq.transpose(1, 2)).squeeze(-1)
            return self.head(torch.cat([summary, static], dim=1))

    return Sequence()


def _train(torch, model, x: np.ndarray, y: np.ndarray, loss_fn, seed: int, y_dtype, device) -> None:
    rng = np.random.default_rng(seed)
    order = rng.permutation(len(x))
    cut = max(1, len(x) // 10)
    hold, train = order[:cut], order[cut:] if len(x) > 20 else order
    model.to(device)
    xt = torch.tensor(x, dtype=torch.float32)
    yt = torch.tensor(y, dtype=y_dtype)
    optimiser = torch.optim.Adam(model.parameters(), lr=2e-3, weight_decay=1e-5)
    best, best_state, waited = float("inf"), None, 0
    for _epoch in range(MAX_EPOCHS):
        model.train()
        shuffled = train[rng.permutation(len(train))]
        for start in range(0, len(shuffled), BATCH):
            batch = shuffled[start:start + BATCH]
            if len(batch) < 2:   # batch norm needs two
                continue
            optimiser.zero_grad()
            loss = loss_fn(model(xt[batch].to(device)), yt[batch].to(device))
            loss.backward()
            optimiser.step()
        model.eval()
        with torch.no_grad():
            held = float(loss_fn(model(xt[hold].to(device)), yt[hold].to(device)))
        if held < best - 1e-6:
            best, waited = held, 0
            best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
        else:
            waited += 1
            if waited >= PATIENCE:
                break
    if best_state is not None:
        model.load_state_dict(best_state)
    model.eval()


def _run(torch, model, x: np.ndarray, device) -> np.ndarray:
    out = []
    with torch.no_grad():
        for start in range(0, len(x), 65_536):
            out.append(model(torch.tensor(x[start:start + 65_536], dtype=torch.float32).to(device)).cpu().numpy())
    return np.concatenate(out) if out else np.empty((0,))


from sklearn.base import BaseEstimator, ClassifierMixin, OutlierMixin, RegressorMixin  # noqa: E402


class _Base(BaseEstimator):
    """``sequence_length``: how many leading feature columns are the time series (set by the service);
    ``device``: "cpu" or "cuda" (set by the service when the GPU is used)."""

    def __init__(self, kind: str = "mlp", seed: int = 7, sequence_length: int = 0, device: str = "cpu"):
        self.kind = kind
        self.seed = seed
        self.sequence_length = sequence_length
        self.device = device

    def _on(self, torch):
        return _device(torch, self.device)


class TorchRegressor(RegressorMixin, _Base):
    def fit(self, x, y):
        torch = _torch()
        torch.manual_seed(self.seed)
        x = np.asarray(x, dtype="float32")
        y = np.asarray(y, dtype="float32")
        self._y_mean, self._y_std = float(y.mean()), float(y.std() or 1.0)
        self.model_ = _network(torch, self.kind, x.shape[1], 1, self.sequence_length)
        _train(torch, self.model_, x, ((y - self._y_mean) / self._y_std)[:, None], torch.nn.MSELoss(), self.seed,
               torch.float32, self._on(torch))
        return self

    def predict(self, x):
        torch = _torch()
        out = _run(torch, self.model_, np.asarray(x, dtype="float32"), self._on(torch))
        return out[:, 0] * self._y_std + self._y_mean


class TorchClassifier(ClassifierMixin, _Base):
    def fit(self, x, y):
        torch = _torch()
        torch.manual_seed(self.seed)
        x = np.asarray(x, dtype="float32")
        self.classes_, codes = np.unique(np.asarray(y), return_inverse=True)
        counts = np.bincount(codes, minlength=len(self.classes_)).astype("float32")
        weights = torch.tensor(counts.sum() / np.maximum(counts, 1) / len(counts), dtype=torch.float32)
        self.model_ = _network(torch, self.kind, x.shape[1], len(self.classes_), self.sequence_length)
        loss = torch.nn.CrossEntropyLoss(weight=weights.to(self._on(torch)))
        _train(torch, self.model_, x, codes, loss, self.seed, torch.long, self._on(torch))
        return self

    def predict_proba(self, x):
        torch = _torch()
        logits = _run(torch, self.model_, np.asarray(x, dtype="float32"), self._on(torch))
        logits = logits - logits.max(axis=1, keepdims=True)
        p = np.exp(logits)
        return p / p.sum(axis=1, keepdims=True)

    def predict(self, x):
        return self.classes_[np.argmax(self.predict_proba(x), axis=1)]


class TorchAutoencoder(OutlierMixin, _Base):
    """Learns to rebuild typical pixels; ``score_samples`` is minus the rebuild error, so lower
    means more anomalous (as scikit-learn's outlier detectors)."""

    def fit(self, x, y=None):
        torch = _torch()
        torch.manual_seed(self.seed)
        nn = torch.nn
        x = np.asarray(x, dtype="float32")
        n = x.shape[1]
        middle = max(1, n // 2)
        self.model_ = nn.Sequential(nn.Linear(n, 32), nn.ReLU(), nn.Linear(32, middle), nn.ReLU(),
                                    nn.Linear(middle, 32), nn.ReLU(), nn.Linear(32, n))
        _train(torch, self.model_, x, x, nn.MSELoss(), self.seed, torch.float32, self._on(torch))
        return self

    def score_samples(self, x):
        torch = _torch()
        x = np.asarray(x, dtype="float32")
        rebuilt = _run(torch, self.model_, x, self._on(torch))
        return -((rebuilt - x) ** 2).mean(axis=1)
