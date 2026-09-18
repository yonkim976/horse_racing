"""FIT-only preprocessing for sealed Top3 experiments."""

import numpy as np


class FitPreprocessor:
    def fit(self, frame, features):
        self.numeric = [x for x in features if x != "regime"]
        a = frame.select(self.numeric).to_numpy().astype(float)
        self.medians = np.array([np.nanmedian(c) if np.isfinite(c).any() else 0.0 for c in a.T])
        a = np.where(np.isfinite(a), a, self.medians)
        self.means = a.mean(axis=0)
        self.scales = a.std(axis=0)
        self.scales[self.scales < 1e-10] = 1
        self.regimes = sorted(frame["regime"].unique().to_list()) if "regime" in features else []
        full = self._full(frame)
        self.keep = full.std(axis=0) > 1e-10
        names = (
            self.numeric
            + [x + "__missing" for x in self.numeric]
            + ["regime=" + x for x in self.regimes]
        )
        self.names = [x for x, keep in zip(names, self.keep, strict=True) if keep]
        return self

    def _full(self, frame):
        a = frame.select(self.numeric).to_numpy().astype(float)
        missing = ~np.isfinite(a)
        a = (np.where(missing, self.medians, a) - self.means) / self.scales
        cats = np.array(
            [[v == c for c in self.regimes] for v in frame["regime"].to_list()], dtype=float
        )
        return np.column_stack([a, missing.astype(float), cats])

    def transform(self, frame):
        return self._full(frame)[:, self.keep]
