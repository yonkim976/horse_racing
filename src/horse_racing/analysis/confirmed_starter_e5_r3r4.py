"""R3/R4-safe temperature analysis and raw-margin LightGBM adapters."""

from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass, field
from typing import Any

import lightgbm as lgb
import numpy as np
from scipy.optimize import brentq

Q_SUM_ATOL = 1e-12
HESSIAN_FLOOR = 1e-6
LOG_T_BOUNDS = (-4.0, 4.0)
BETA_BOUNDS = (math.exp(-4.0), math.exp(4.0))
BETA_XTOL = 1e-12
BETA_RTOL = 4.0 * np.finfo(float).eps
BETA_MAXITER = 200


class E5R3R4ContractError(ValueError):
    """Raised when an R3/R4 mathematical or API contract fails."""


def validate_groups(groups: np.ndarray, row_count: int) -> np.ndarray:
    values = np.asarray(groups)
    if values.ndim != 1 or values.size == 0:
        raise E5R3R4ContractError("groups must be non-empty and one-dimensional")
    if not np.isfinite(values).all() or not np.equal(values, np.floor(values)).all():
        raise E5R3R4ContractError("groups must contain finite integers")
    checked = values.astype(np.int64)
    if (checked <= 0).any() or int(checked.sum()) != row_count:
        raise E5R3R4ContractError("positive group sizes must sum exactly to row count")
    return checked


def group_slices(groups: np.ndarray, row_count: int) -> list[slice]:
    checked = validate_groups(groups, row_count)
    offsets = np.concatenate(([0], np.cumsum(checked)))
    return [
        slice(int(left), int(right)) for left, right in zip(offsets[:-1], offsets[1:], strict=True)
    ]


def soft_labels_from_winners(winners: np.ndarray, groups: np.ndarray) -> np.ndarray:
    labels = np.asarray(winners)
    if labels.ndim != 1 or not np.isfinite(labels).all() or not np.isin(labels, [0, 1]).all():
        raise E5R3R4ContractError("winner labels must be a finite 0/1 vector")
    q = np.zeros(labels.size, dtype=np.float64)
    for block in group_slices(groups, labels.size):
        count = int(labels[block].sum())
        if count == 0:
            raise E5R3R4ContractError("every race must contain an official winner")
        q[block] = labels[block].astype(np.float64) / count
        total = float(q[block].sum())
        if not math.isclose(total, 1.0, rel_tol=0.0, abs_tol=Q_SUM_ATOL):
            raise E5R3R4ContractError("soft-label sum violates absolute-only tolerance")
        q[block] /= total
    return q


@dataclass(frozen=True)
class BetaEvaluation:
    beta: float
    log_temperature: float
    temperature: float
    objective: float
    derivative: float
    second_derivative: float


def evaluate_beta(
    logits: np.ndarray, winners: np.ndarray, groups: np.ndarray, beta: float
) -> BetaEvaluation:
    """Evaluate equal-race CE and beta derivatives in per-race shifted coordinates."""
    scores = np.asarray(logits, dtype=np.float64)
    if scores.ndim != 1 or not np.isfinite(scores).all():
        raise E5R3R4ContractError("logits must be a finite one-dimensional vector")
    if not math.isfinite(beta) or beta <= 0.0:
        raise E5R3R4ContractError("beta must be finite and positive")
    q = soft_labels_from_winners(winners, groups)
    losses: list[float] = []
    derivatives: list[float] = []
    curvatures: list[float] = []
    for block in group_slices(groups, scores.size):
        shifted = scores[block] - scores[block].max()
        scaled = beta * shifted
        log_normalizer = float(np.logaddexp.reduce(scaled))
        probabilities = np.exp(scaled - log_normalizer)
        expected_score = float(np.dot(probabilities, shifted))
        q_score = float(np.dot(q[block], shifted))
        losses.append(log_normalizer - beta * q_score)
        derivatives.append(expected_score - q_score)
        curvatures.append(float(np.dot(probabilities, shifted * shifted) - expected_score**2))
    return BetaEvaluation(
        beta=beta,
        log_temperature=-math.log(beta),
        temperature=1.0 / beta,
        objective=float(np.mean(losses)),
        derivative=float(np.mean(derivatives)),
        second_derivative=float(np.mean(curvatures)),
    )


@dataclass(frozen=True)
class TemperatureDiagnostic:
    status: str
    structural_flat: bool
    approximate_flat_allowed: bool
    lower_beta_endpoint: BetaEvaluation
    upper_beta_endpoint: BetaEvaluation
    solution: BetaEvaluation
    optimizer: str
    optimizer_iterations: int
    derivative_sign_rule: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def diagnose_temperature(
    logits: np.ndarray, winners: np.ndarray, groups: np.ndarray
) -> TemperatureDiagnostic:
    """Classify the bounded optimum by convex beta endpoint derivatives."""
    scores = np.asarray(logits, dtype=np.float64)
    blocks = group_slices(groups, scores.size)
    structural_flat = all(np.equal(scores[block], scores[block][0]).all() for block in blocks)
    beta_low, beta_high = BETA_BOUNDS
    lower = evaluate_beta(scores, winners, groups, beta_low)
    upper = evaluate_beta(scores, winners, groups, beta_high)
    if not all(
        math.isfinite(value)
        for endpoint in (lower, upper)
        for value in (endpoint.objective, endpoint.derivative, endpoint.second_derivative)
    ):
        raise E5R3R4ContractError("temperature endpoint evaluation is non-finite")
    rule = (
        "convex in beta: d(beta_low)>=0 -> logT upper boundary; "
        "d(beta_high)<=0 -> logT lower boundary; otherwise unique derivative root"
    )
    if structural_flat:
        solution = evaluate_beta(scores, winners, groups, 1.0)
        return TemperatureDiagnostic(
            "flat_use_T1", True, False, lower, upper, solution, "structural", 0, rule
        )
    if lower.derivative >= 0.0:
        return TemperatureDiagnostic(
            "boundary_logT_upper",
            False,
            False,
            lower,
            upper,
            lower,
            "endpoint_optimality",
            0,
            rule,
        )
    if upper.derivative <= 0.0:
        return TemperatureDiagnostic(
            "boundary_logT_lower",
            False,
            False,
            lower,
            upper,
            upper,
            "endpoint_optimality",
            0,
            rule,
        )
    calls = 0

    def derivative(beta: float) -> float:
        nonlocal calls
        calls += 1
        value = evaluate_beta(scores, winners, groups, beta).derivative
        if not math.isfinite(value):
            raise E5R3R4ContractError("temperature derivative became non-finite")
        return value

    try:
        root = brentq(
            derivative,
            beta_low,
            beta_high,
            xtol=BETA_XTOL,
            rtol=BETA_RTOL,
            maxiter=BETA_MAXITER,
        )
    except (RuntimeError, ValueError) as exc:
        raise E5R3R4ContractError("temperature derivative root solve failed") from exc
    solution = evaluate_beta(scores, winners, groups, float(root))
    return TemperatureDiagnostic(
        "interior_optimum", False, False, lower, upper, solution, "scipy.brentq", calls, rule
    )


def fit_temperature(logits: np.ndarray, winners: np.ndarray, groups: np.ndarray) -> float:
    diagnostic = diagnose_temperature(logits, winners, groups)
    if diagnostic.status.startswith("boundary_"):
        raise E5R3R4ContractError(f"temperature optimum is a boundary: {diagnostic.status}")
    return diagnostic.solution.temperature


def stable_sigmoid(logits: np.ndarray) -> np.ndarray:
    scores = np.asarray(logits, dtype=np.float64)
    if not np.isfinite(scores).all():
        raise E5R3R4ContractError("binary logits must be finite")
    result = np.empty_like(scores)
    positive = scores >= 0.0
    result[positive] = 1.0 / (1.0 + np.exp(-scores[positive]))
    exponentials = np.exp(scores[~positive])
    result[~positive] = exponentials / (1.0 + exponentials)
    return result


def binary_loss_gradient_hessian(
    logits: np.ndarray, labels: np.ndarray, weights: np.ndarray
) -> tuple[float, np.ndarray, np.ndarray]:
    """Weighted Bernoulli loss and exact per-row raw-margin derivatives."""
    scores = np.asarray(logits, dtype=np.float64)
    y = np.asarray(labels, dtype=np.float64)
    w = np.asarray(weights, dtype=np.float64)
    if scores.ndim != 1 or y.shape != scores.shape or w.shape != scores.shape:
        raise E5R3R4ContractError("binary arrays must be same-length vectors")
    if not np.isfinite(y).all() or not np.isin(y, [0.0, 1.0]).all():
        raise E5R3R4ContractError("binary labels must be finite zero or one")
    if not np.isfinite(w).all() or (w <= 0.0).any():
        raise E5R3R4ContractError("binary weights must be finite and positive")
    probabilities = stable_sigmoid(scores)
    losses = np.where(y == 1.0, np.logaddexp(0.0, -scores), np.logaddexp(0.0, scores))
    gradient = w * (probabilities - y)
    hessian = w * probabilities * (1.0 - probabilities)
    return float(np.dot(w, losses)), gradient, hessian


def grouped_soft_label_ce(logits: np.ndarray, winners: np.ndarray, groups: np.ndarray) -> float:
    return evaluate_beta(logits, winners, groups, 1.0).objective


def grouped_softmax(logits: np.ndarray, groups: np.ndarray) -> np.ndarray:
    scores = np.asarray(logits, dtype=np.float64)
    if scores.ndim != 1 or not np.isfinite(scores).all():
        raise E5R3R4ContractError("logits must be a finite one-dimensional vector")
    result = np.empty_like(scores)
    for block in group_slices(groups, scores.size):
        shifted = scores[block] - scores[block].max()
        exponentials = np.exp(shifted)
        result[block] = exponentials / exponentials.sum()
    return result


def _array_evidence(values: np.ndarray) -> dict[str, Any]:
    array = np.asarray(values)
    return {
        "shape": list(array.shape),
        "dtype": str(array.dtype),
        "min": float(array.min()),
        "max": float(array.max()),
        "head": array[:12].tolist(),
        "sha256": hashlib.sha256(np.ascontiguousarray(array).tobytes()).hexdigest(),
    }


@dataclass
class CallbackEvidence:
    objective_calls: list[dict[str, Any]] = field(default_factory=list)
    metric_calls: list[dict[str, Any]] = field(default_factory=list)


class NativeBinaryObjective:
    """Weighted Bernoulli custom objective that preserves raw-margin evaluation."""

    def __init__(self, evidence: CallbackEvidence):
        self.evidence = evidence

    def __deepcopy__(self, memo: dict[int, Any]) -> NativeBinaryObjective:
        del memo
        return self

    def __call__(
        self, predictions: np.ndarray, dataset: lgb.Dataset
    ) -> tuple[np.ndarray, np.ndarray]:
        labels = dataset.get_label()
        weights = dataset.get_weight()
        groups = dataset.get_group()
        if weights is None or groups is None:
            raise E5R3R4ContractError("BINARY requires explicit weights and groups")
        validate_groups(groups, len(predictions))
        loss, gradient, hessian = binary_loss_gradient_hessian(predictions, labels, weights)
        self.evidence.objective_calls.append(
            {
                "raw_margins": _array_evidence(predictions),
                "labels": _array_evidence(labels),
                "weights": _array_evidence(weights),
                "groups": _array_evidence(groups),
                "weighted_loss": loss,
            }
        )
        return gradient, hessian


class NativeRaceSoftmaxObjective:
    """Race-softmax objective whose actual policy requires Dataset weight=None."""

    def __init__(self, evidence: CallbackEvidence):
        self.evidence = evidence

    def __deepcopy__(self, memo: dict[int, Any]) -> NativeRaceSoftmaxObjective:
        del memo
        return self

    def __call__(
        self, predictions: np.ndarray, dataset: lgb.Dataset
    ) -> tuple[np.ndarray, np.ndarray]:
        labels = dataset.get_label()
        groups = dataset.get_group()
        weights = dataset.get_weight()
        if groups is None or weights is not None:
            raise E5R3R4ContractError("RACE_SOFTMAX requires explicit groups and weight=None")
        q = soft_labels_from_winners(labels, groups)
        gradient = np.empty(len(predictions), dtype=np.float64)
        hessian = np.empty(len(predictions), dtype=np.float64)
        floor_count = 0
        for block in group_slices(groups, len(predictions)):
            shifted = predictions[block] - np.max(predictions[block])
            exponentials = np.exp(shifted)
            probabilities = exponentials / exponentials.sum()
            exact_hessian = probabilities * (1.0 - probabilities)
            gradient[block] = probabilities - q[block]
            hessian[block] = np.maximum(exact_hessian, HESSIAN_FLOOR)
            floor_count += int((exact_hessian < HESSIAN_FLOOR).sum())
        self.evidence.objective_calls.append(
            {
                "raw_margins": _array_evidence(predictions),
                "labels": _array_evidence(labels),
                "weights": None,
                "groups": _array_evidence(groups),
                "q_dtype": str(q.dtype),
                "q_group_sums": [float(q[block].sum()) for block in group_slices(groups, q.size)],
                "hessian_floor_count": floor_count,
            }
        )
        return gradient, hessian


class NativeRawRaceMetric:
    """Common metric that accepts raw margin directly for both custom objectives."""

    def __init__(self, evidence: CallbackEvidence):
        self.evidence = evidence

    def __call__(self, predictions: np.ndarray, dataset: lgb.Dataset) -> tuple[str, float, bool]:
        labels = dataset.get_label()
        groups = dataset.get_group()
        if groups is None or not np.isfinite(predictions).all():
            raise E5R3R4ContractError("raw metric requires finite margins and explicit groups")
        value = grouped_soft_label_ce(predictions, labels, groups)
        self.evidence.metric_calls.append(
            {
                "raw_margins": _array_evidence(predictions),
                "labels": _array_evidence(labels),
                "weights": (
                    None if dataset.get_weight() is None else _array_evidence(dataset.get_weight())
                ),
                "groups": _array_evidence(groups),
                "metric": value,
            }
        )
        return "race_equal_soft_label_ce", value, False
