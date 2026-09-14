"""Race-softmax math and native LightGBM adapters for E5 research."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Any, Literal

import lightgbm as lgb
import numpy as np
from scipy.optimize import minimize_scalar

Q_SUM_ATOL = 1e-12
HESSIAN_FLOOR = 1e-6
TEMPERATURE_LOG_BOUNDS = (-4.0, 4.0)
TEMPERATURE_XATOL = 1e-8
TEMPERATURE_MAXITER = 500


class E5ContractError(ValueError):
    """Raised when mathematical or LightGBM group contracts are violated."""


def validate_groups(groups: np.ndarray, row_count: int) -> np.ndarray:
    """Return validated integer group sizes whose sum exactly matches the rows."""
    values = np.asarray(groups)
    if values.ndim != 1 or values.size == 0:
        raise E5ContractError("groups must be a non-empty one-dimensional array")
    if not np.issubdtype(values.dtype, np.integer):
        if not np.isfinite(values).all() or not np.equal(values, np.floor(values)).all():
            raise E5ContractError("groups must contain finite integers")
    values = values.astype(np.int64, copy=False)
    if (values <= 0).any():
        raise E5ContractError("every group size must be positive")
    if int(values.sum()) != row_count:
        raise E5ContractError(f"group sum {int(values.sum())} does not match row count {row_count}")
    return values


def group_slices(groups: np.ndarray, row_count: int) -> list[slice]:
    """Translate validated contiguous group sizes into row slices."""
    checked = validate_groups(groups, row_count)
    offsets = np.concatenate(([0], np.cumsum(checked)))
    return [
        slice(int(left), int(right)) for left, right in zip(offsets[:-1], offsets[1:], strict=True)
    ]


def normalize_soft_labels(labels: np.ndarray, *, atol: float = Q_SUM_ATOL) -> np.ndarray:
    """Validate q with absolute-only tolerance, then normalize accepted rounding error.

    Normalizing every accepted vector makes the CE formula, gradient ``p-q``, and
    Hessian contract all use exactly the same sum-one q.
    """
    values = np.asarray(labels, dtype=np.float64)
    if values.ndim != 1 or values.size == 0:
        raise E5ContractError("soft labels must be a non-empty one-dimensional array")
    if not np.isfinite(values).all() or (values < 0.0).any():
        raise E5ContractError("soft labels must be finite and nonnegative")
    total = float(values.sum())
    if not math.isclose(total, 1.0, rel_tol=0.0, abs_tol=atol):
        raise E5ContractError(f"soft-label sum {total} is outside absolute tolerance {atol}")
    return values / total


@dataclass(frozen=True)
class RaceSoftmaxDerivatives:
    loss: float
    probabilities: np.ndarray
    gradient: np.ndarray
    full_hessian: np.ndarray
    exact_hessian_diagonal: np.ndarray
    trainer_hessian_diagonal: np.ndarray
    hessian_floor_count: int


def race_softmax_derivatives(
    logits: np.ndarray,
    soft_labels: np.ndarray,
    *,
    hessian_floor: float = HESSIAN_FLOOR,
) -> RaceSoftmaxDerivatives:
    """Compute stable CE, exact derivatives, and the declared trainer approximation."""
    scores = np.asarray(logits, dtype=np.float64)
    if scores.ndim != 1 or scores.size == 0 or not np.isfinite(scores).all():
        raise E5ContractError("logits must be a non-empty finite one-dimensional array")
    q = normalize_soft_labels(soft_labels)
    if q.shape != scores.shape:
        raise E5ContractError("logits and soft labels must have the same shape")
    if not math.isfinite(hessian_floor) or hessian_floor <= 0.0:
        raise E5ContractError("hessian_floor must be finite and positive")

    shifted = scores - scores.max()
    exponentials = np.exp(shifted)
    probabilities = exponentials / exponentials.sum()
    log_normalizer = math.log(float(exponentials.sum()))
    loss = float(log_normalizer - np.dot(q, shifted))
    gradient = probabilities - q
    full_hessian = np.diag(probabilities) - np.outer(probabilities, probabilities)
    exact_diagonal = np.diag(full_hessian).copy()
    trainer_diagonal = np.maximum(exact_diagonal, hessian_floor)
    return RaceSoftmaxDerivatives(
        loss=loss,
        probabilities=probabilities,
        gradient=gradient,
        full_hessian=full_hessian,
        exact_hessian_diagonal=exact_diagonal,
        trainer_hessian_diagonal=trainer_diagonal,
        hessian_floor_count=int((exact_diagonal < hessian_floor).sum()),
    )


def soft_labels_from_winners(winner_indicators: np.ndarray, groups: np.ndarray) -> np.ndarray:
    """Build float64 per-race uniform winner labels from exact 0/1 indicators."""
    winners = np.asarray(winner_indicators)
    if winners.ndim != 1 or not np.isfinite(winners).all():
        raise E5ContractError("winner indicators must be a finite one-dimensional array")
    if not np.isin(winners, [0.0, 1.0]).all():
        raise E5ContractError("winner indicators must contain only zero or one")
    q = np.zeros(winners.size, dtype=np.float64)
    for block in group_slices(groups, winners.size):
        count = int(winners[block].sum())
        if count < 1:
            raise E5ContractError("every race must contain at least one official winner")
        q[block] = winners[block].astype(np.float64) / count
        q[block] = normalize_soft_labels(q[block])
    return q


def grouped_softmax(
    logits: np.ndarray, groups: np.ndarray, *, temperature: float = 1.0
) -> np.ndarray:
    """Apply stable softmax independently to each declared contiguous race group."""
    scores = np.asarray(logits, dtype=np.float64)
    if scores.ndim != 1 or not np.isfinite(scores).all():
        raise E5ContractError("logits must be a finite one-dimensional array")
    if not math.isfinite(temperature) or temperature <= 0.0:
        raise E5ContractError("temperature must be finite and positive")
    result = np.empty_like(scores)
    for block in group_slices(groups, scores.size):
        shifted = scores[block] / temperature
        shifted -= shifted.max()
        exponentials = np.exp(shifted)
        result[block] = exponentials / exponentials.sum()
    return result


def grouped_soft_label_ce(
    logits: np.ndarray,
    winner_indicators: np.ndarray,
    groups: np.ndarray,
    *,
    temperature: float = 1.0,
) -> float:
    """Return the equal-race mean soft-label CE."""
    scores = np.asarray(logits, dtype=np.float64) / temperature
    q = soft_labels_from_winners(winner_indicators, groups)
    losses = [
        race_softmax_derivatives(scores[block], q[block]).loss
        for block in group_slices(groups, scores.size)
    ]
    return float(np.mean(losses))


def race_softmax_objective_arrays(
    logits: np.ndarray,
    winner_indicators: np.ndarray,
    groups: np.ndarray,
    *,
    weights: np.ndarray | None,
    hessian_floor: float = HESSIAN_FLOOR,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Build un-averaged per-race gradients and floored diagonal Hessians."""
    scores = np.asarray(logits, dtype=np.float64)
    checked_groups = validate_groups(groups, scores.size)
    q = soft_labels_from_winners(winner_indicators, checked_groups)
    if weights is None:
        checked_weights = np.ones(scores.size, dtype=np.float64)
    else:
        checked_weights = np.asarray(weights, dtype=np.float64)
        if checked_weights.shape != scores.shape or not np.isfinite(checked_weights).all():
            raise E5ContractError("weights must be finite and match logits")
        if (checked_weights <= 0.0).any():
            raise E5ContractError("weights must be positive")
    gradient = np.empty_like(scores)
    hessian = np.empty_like(scores)
    floor_count = 0
    for block in group_slices(checked_groups, scores.size):
        group_weight = checked_weights[block]
        if not np.equal(group_weight, group_weight[0]).all():
            raise E5ContractError("RACE_SOFTMAX requires one constant weight per race")
        derivatives = race_softmax_derivatives(scores[block], q[block], hessian_floor=hessian_floor)
        gradient[block] = derivatives.gradient * group_weight[0]
        hessian[block] = derivatives.trainer_hessian_diagonal * group_weight[0]
        floor_count += derivatives.hessian_floor_count
    return (
        gradient,
        hessian,
        {
            "group_values": checked_groups.tolist(),
            "group_sum": int(checked_groups.sum()),
            "q_dtype": str(q.dtype),
            "q_third_values": sorted(set(q[np.isclose(q, 1.0 / 3.0)].tolist())),
            "q_group_sums": [
                float(q[block].sum()) for block in group_slices(checked_groups, q.size)
            ],
            "hessian_floor": hessian_floor,
            "hessian_floor_count": floor_count,
        },
    )


def _array_evidence(values: np.ndarray) -> dict[str, Any]:
    array = np.asarray(values)
    contiguous = np.ascontiguousarray(array)
    return {
        "shape": list(array.shape),
        "dtype": str(array.dtype),
        "min": float(array.min()),
        "max": float(array.max()),
        "head": array[:12].tolist(),
        "sha256": hashlib.sha256(contiguous.tobytes()).hexdigest(),
    }


@dataclass
class CallbackEvidence:
    objective_calls: list[dict[str, Any]] = field(default_factory=list)
    evaluation_calls: list[dict[str, Any]] = field(default_factory=list)

    def compact(self) -> dict[str, Any]:
        return {
            "objective_call_count": len(self.objective_calls),
            "evaluation_call_count": len(self.evaluation_calls),
            "objective_first": self.objective_calls[0] if self.objective_calls else None,
            "objective_last": self.objective_calls[-1] if self.objective_calls else None,
            "evaluation_first": self.evaluation_calls[0] if self.evaluation_calls else None,
            "evaluation_last": self.evaluation_calls[-1] if self.evaluation_calls else None,
        }


class NativeRaceSoftmaxObjective:
    """Public ``lightgbm.train`` custom objective backed by Dataset group metadata."""

    def __init__(self, evidence: CallbackEvidence, *, hessian_floor: float = HESSIAN_FLOOR):
        self.evidence = evidence
        self.hessian_floor = hessian_floor

    def __deepcopy__(self, memo: dict[int, Any]) -> NativeRaceSoftmaxObjective:
        """Keep one recorder when ``lightgbm.train`` deep-copies its params."""
        del memo
        return self

    def __call__(
        self, predictions: np.ndarray, dataset: lgb.Dataset
    ) -> tuple[np.ndarray, np.ndarray]:
        labels = dataset.get_label()
        groups = dataset.get_group()
        weights = dataset.get_weight()
        if groups is None:
            raise E5ContractError("custom objective requires explicit Dataset group")
        gradient, hessian, details = race_softmax_objective_arrays(
            predictions,
            labels,
            groups,
            weights=weights,
            hessian_floor=self.hessian_floor,
        )
        self.evidence.objective_calls.append(
            {
                "labels": _array_evidence(labels),
                "raw_margins": _array_evidence(predictions),
                "weights": None if weights is None else _array_evidence(weights),
                "groups": _array_evidence(groups),
                "gradient": _array_evidence(gradient),
                "trainer_hessian": _array_evidence(hessian),
                **details,
            }
        )
        return gradient, hessian


class NativeRaceMetric:
    """Single race-equal soft-label CE metric with explicit callback semantics."""

    def __init__(
        self,
        evidence: CallbackEvidence,
        *,
        prediction_semantics: Literal["binary_probability", "raw_margin"],
    ):
        self.evidence = evidence
        self.prediction_semantics = prediction_semantics

    def __call__(self, predictions: np.ndarray, dataset: lgb.Dataset) -> tuple[str, float, bool]:
        labels = dataset.get_label()
        groups = dataset.get_group()
        weights = dataset.get_weight()
        if groups is None:
            raise E5ContractError("custom metric requires explicit Dataset group")
        callback_values = np.asarray(predictions, dtype=np.float64)
        if self.prediction_semantics == "binary_probability":
            clipped = np.clip(callback_values, 1e-15, 1.0 - 1e-15)
            logits = np.log(clipped) - np.log1p(-clipped)
        else:
            logits = callback_values
        value = grouped_soft_label_ce(logits, labels, groups)
        self.evidence.evaluation_calls.append(
            {
                "prediction_semantics": self.prediction_semantics,
                "labels": _array_evidence(labels),
                "callback_predictions": _array_evidence(callback_values),
                "derived_or_raw_logits": _array_evidence(logits),
                "weights": None if weights is None else _array_evidence(weights),
                "groups": _array_evidence(groups),
                "group_sum": int(np.asarray(groups).sum()),
                "metric": value,
            }
        )
        return "race_equal_soft_label_ce", value, False


@dataclass(frozen=True)
class TemperatureFit:
    temperature: float
    log_temperature: float
    objective: float
    status: str
    optimizer_success: bool
    boundary_solution: bool
    iterations: int


def fit_temperature(
    logits: np.ndarray, winner_indicators: np.ndarray, groups: np.ndarray
) -> TemperatureFit:
    """Fit one bounded log-temperature with deterministic flat/failure handling."""
    scores = np.asarray(logits, dtype=np.float64)
    validate_groups(groups, scores.size)
    soft_labels_from_winners(winner_indicators, groups)
    lower, upper = TEMPERATURE_LOG_BOUNDS

    def objective(log_temperature: float) -> float:
        return grouped_soft_label_ce(
            scores,
            winner_indicators,
            groups,
            temperature=math.exp(log_temperature),
        )

    probe_values = np.asarray([objective(lower), objective(0.0), objective(upper)])
    if not np.isfinite(probe_values).all():
        raise E5ContractError("temperature objective is non-finite")
    if float(probe_values.max() - probe_values.min()) <= 1e-12:
        return TemperatureFit(1.0, 0.0, float(probe_values[1]), "flat_use_T1", True, False, 0)
    result = minimize_scalar(
        objective,
        method="bounded",
        bounds=TEMPERATURE_LOG_BOUNDS,
        options={"xatol": TEMPERATURE_XATOL, "maxiter": TEMPERATURE_MAXITER},
    )
    if not result.success or not math.isfinite(float(result.fun)):
        raise E5ContractError(f"temperature optimization failed: {result.message}")
    log_temperature = float(result.x)
    boundary = min(log_temperature - lower, upper - log_temperature) <= 10 * TEMPERATURE_XATOL
    if boundary:
        raise E5ContractError("temperature optimum is at the declared search boundary")
    return TemperatureFit(
        temperature=math.exp(log_temperature),
        log_temperature=log_temperature,
        objective=float(result.fun),
        status="interior_optimum",
        optimizer_success=True,
        boundary_solution=False,
        iterations=int(result.nfev),
    )


def json_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()
