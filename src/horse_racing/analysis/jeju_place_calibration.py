"""Positive Platt calibration for per-entry official Top3 probabilities.

The calibrator maps an arbitrary model score to a binary probability with
``sigmoid(exp(log_scale) * score + intercept)``.  It is intentionally separate
from the race-level Plackett--Luce temperature: these probabilities are useful
for entry-level calibration diagnostics and are not normalized to sum to three
within a race.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit, logsumexp

_LOGIT_CLIP = 700.0


def _validate_training_inputs(
    scores: Sequence[float] | np.ndarray,
    labels: Sequence[float] | np.ndarray,
    sample_weight: Sequence[float] | np.ndarray | None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    values = np.asarray(scores, dtype=float)
    targets = np.asarray(labels, dtype=float)
    if values.ndim != 1 or targets.ndim != 1:
        raise ValueError("scores and labels must be one-dimensional")
    if len(values) == 0 or len(values) != len(targets):
        raise ValueError("scores and labels must be non-empty and have equal length")
    if not np.all(np.isfinite(values)):
        raise ValueError("scores must contain only finite values")
    if not np.all(np.isfinite(targets)) or not np.all((targets == 0.0) | (targets == 1.0)):
        raise ValueError("labels must contain only finite 0/1 values")

    if sample_weight is None:
        weights = np.ones(len(values), dtype=float)
    else:
        weights = np.asarray(sample_weight, dtype=float)
        if weights.ndim != 1 or len(weights) != len(values):
            raise ValueError("sample_weight must be one-dimensional with one value per row")
        if not np.all(np.isfinite(weights)) or np.any(weights < 0):
            raise ValueError("sample_weight must contain finite non-negative values")
    if not np.isfinite(weights.sum()) or float(weights.sum()) <= 0:
        raise ValueError("sample_weight must have a positive finite sum")
    return values, targets, weights


def _safe_logits(params: np.ndarray, scores: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return finite clipped logits and a mask for the differentiable region."""
    log_scale, intercept = params
    scale = float(np.exp(log_scale))
    with np.errstate(over="ignore", invalid="ignore"):
        raw = scale * scores + intercept
    active = np.isfinite(raw) & (raw > -_LOGIT_CLIP) & (raw < _LOGIT_CLIP)
    return np.clip(raw, -_LOGIT_CLIP, _LOGIT_CLIP), active


def _objective_and_gradient(
    params: np.ndarray,
    scores: np.ndarray,
    labels: np.ndarray,
    sample_weight: np.ndarray,
) -> tuple[float, np.ndarray]:
    logits, active = _safe_logits(params, scores)
    weight_total = float(sample_weight.sum())
    # log(sigmoid(z)) and log(1-sigmoid(z)) in one stable expression.
    per_row_loss = logsumexp(np.stack((np.zeros_like(logits), logits)), axis=0) - labels * logits
    loss = float(np.dot(sample_weight, per_row_loss) / weight_total)
    residual = expit(logits) - labels
    residual = np.where(active, residual, 0.0)
    scale = float(np.exp(params[0]))
    gradient = np.array(
        [
            np.dot(sample_weight, residual * scale * scores),
            np.dot(sample_weight, residual),
        ],
        dtype=float,
    )
    gradient /= weight_total
    return loss, gradient


def positive_platt_objective_and_gradient(
    params: Sequence[float] | np.ndarray,
    scores: Sequence[float] | np.ndarray,
    labels: Sequence[float] | np.ndarray,
    sample_weight: Sequence[float] | np.ndarray | None = None,
) -> tuple[float, np.ndarray]:
    """Evaluate weighted binary log loss and its analytic parameter gradient."""
    values, targets, weights = _validate_training_inputs(scores, labels, sample_weight)
    parameters = np.asarray(params, dtype=float)
    if parameters.ndim != 1 or len(parameters) != 2 or not np.all(np.isfinite(parameters)):
        raise ValueError("params must contain finite [log_scale, intercept]")
    return _objective_and_gradient(parameters, values, targets, weights)


class PositivePlattCalibrator:
    """Bounded positive-slope logistic calibrator for official Top3 labels."""

    def fit(
        self,
        scores: Sequence[float] | np.ndarray,
        labels: Sequence[float] | np.ndarray,
        sample_weight: Sequence[float] | np.ndarray | None = None,
    ) -> PositivePlattCalibrator:
        values, targets, weights = _validate_training_inputs(scores, labels, sample_weight)

        def objective(params: np.ndarray) -> tuple[float, np.ndarray]:
            return _objective_and_gradient(params, values, targets, weights)

        result = minimize(
            objective,
            np.zeros(2, dtype=float),
            method="L-BFGS-B",
            jac=True,
            bounds=[(-4.0, 4.0), (-10.0, 10.0)],
            options={"maxiter": 150, "ftol": 1e-12, "gtol": 1e-8, "maxls": 50},
        )
        self.log_scale_ = float(result.x[0])
        self.scale_ = float(np.exp(self.log_scale_))
        self.intercept_ = float(result.x[1])
        self.objective_ = float(result.fun)
        self.n_iter_ = int(getattr(result, "nit", 0))
        self.success_ = bool(result.success)
        self.message_ = str(result.message)
        return self

    def predict(self, scores: Sequence[float] | np.ndarray) -> np.ndarray:
        """Return calibrated positive-class probabilities aligned to ``scores``."""
        if not hasattr(self, "scale_"):
            raise ValueError("PositivePlattCalibrator is not fitted")
        values = np.asarray(scores, dtype=float)
        if values.ndim != 1:
            raise ValueError("scores must be one-dimensional")
        if not np.all(np.isfinite(values)):
            raise ValueError("scores must contain only finite values")
        with np.errstate(over="ignore", invalid="ignore"):
            logits = self.scale_ * values + self.intercept_
        return expit(np.clip(logits, -_LOGIT_CLIP, _LOGIT_CLIP))

    @property
    def objective(self) -> float:
        if not hasattr(self, "objective_"):
            raise ValueError("PositivePlattCalibrator is not fitted")
        return self.objective_

    @property
    def n_iter(self) -> int:
        if not hasattr(self, "n_iter_"):
            raise ValueError("PositivePlattCalibrator is not fitted")
        return self.n_iter_

    @property
    def success(self) -> bool:
        if not hasattr(self, "success_"):
            raise ValueError("PositivePlattCalibrator is not fitted")
        return self.success_


__all__ = ["PositivePlattCalibrator", "positive_platt_objective_and_gradient"]
