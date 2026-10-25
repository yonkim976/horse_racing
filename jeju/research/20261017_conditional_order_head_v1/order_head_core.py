"""Minimal conditional Plackett-Luce math and H1-only feature transform."""

from __future__ import annotations

import itertools
from dataclasses import asdict, dataclass
from typing import Sequence

import numpy as np
from scipy.optimize import minimize
from scipy.special import logsumexp


RAW_COLUMNS = (
    "score",
    "hist_s1f_relpos_mean5",
    "hist_s1f_relpos_n",
    "hist_s1f_to_c4_forward_mean5",
    "hist_s1f_to_c4_pair_n",
    "hist_c4_to_g1f_forward_mean5",
    "hist_c4_to_g1f_pair_n",
)
MEAN_COLUMNS = (
    "hist_s1f_relpos_mean5",
    "hist_s1f_to_c4_forward_mean5",
    "hist_c4_to_g1f_forward_mean5",
)
FEATURE_NAMES = RAW_COLUMNS + tuple(f"missing:{name}" for name in MEAN_COLUMNS)
RIDGE = 0.01
TEMPERATURE_BOUNDS = (0.05, 20.0)
PL_ORDERS = tuple(itertools.permutations(range(3)))


def race_weights(frame) -> np.ndarray:
    field_sizes = frame["field_n"].to_numpy(dtype=float)
    if not np.isfinite(field_sizes).all() or (field_sizes < 1).any():
        raise ValueError("invalid field_n for race-equal weighting")
    return 1.0 / field_sizes


@dataclass(frozen=True)
class H1Standardizer:
    feature_names: tuple[str, ...]
    impute_means: tuple[float, ...]
    centers: tuple[float, ...]
    scales: tuple[float, ...]
    degenerate: tuple[bool, ...]
    h1_rows: int
    h1_races: int

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def fit(cls, h1_frame) -> "H1Standardizer":
        weights = race_weights(h1_frame)
        raw = np.empty((len(h1_frame), len(RAW_COLUMNS)), dtype=float)
        impute = np.zeros(len(RAW_COLUMNS), dtype=float)
        for column_index, column in enumerate(RAW_COLUMNS):
            values = h1_frame[column].to_numpy(dtype=float, na_value=np.nan)
            if column in MEAN_COLUMNS:
                observed = np.isfinite(values)
                if not observed.any():
                    raise ValueError(f"H1 column has no observed values: {column}")
                impute[column_index] = float(np.average(values[observed], weights=weights[observed]))
                values = np.where(observed, values, impute[column_index])
            else:
                if not np.isfinite(values).all():
                    raise ValueError(f"H1 non-mean column is not finite: {column}")
                impute[column_index] = float(np.average(values, weights=weights))
            raw[:, column_index] = values

        indicators = np.column_stack([
            h1_frame[column].isna().to_numpy(dtype=float) for column in MEAN_COLUMNS
        ])
        complete = np.column_stack([raw, indicators])
        centers = np.average(complete, axis=0, weights=weights)
        variances = np.average((complete - centers) ** 2, axis=0, weights=weights)
        scales = np.sqrt(np.maximum(variances, 0.0))
        degenerate = scales <= 1e-12
        scales[degenerate] = 1.0
        return cls(
            feature_names=FEATURE_NAMES,
            impute_means=tuple(float(value) for value in impute),
            centers=tuple(float(value) for value in centers),
            scales=tuple(float(value) for value in scales),
            degenerate=tuple(bool(value) for value in degenerate),
            h1_rows=int(len(h1_frame)),
            h1_races=int(h1_frame["race_id"].nunique()),
        )

    def transform(self, frame) -> np.ndarray:
        raw = np.empty((len(frame), len(RAW_COLUMNS)), dtype=float)
        for column_index, column in enumerate(RAW_COLUMNS):
            values = frame[column].to_numpy(dtype=float, na_value=np.nan)
            if column in MEAN_COLUMNS:
                values = np.where(np.isfinite(values), values, self.impute_means[column_index])
            if not np.isfinite(values).all():
                raise ValueError(f"non-finite transformed source column: {column}")
            raw[:, column_index] = values
        indicators = np.column_stack([
            frame[column].isna().to_numpy(dtype=float) for column in MEAN_COLUMNS
        ])
        complete = np.column_stack([raw, indicators])
        center = np.asarray(self.centers, dtype=float)
        scale = np.asarray(self.scales, dtype=float)
        transformed = (complete - center) / scale
        if any(self.degenerate):
            transformed[:, np.asarray(self.degenerate, dtype=bool)] = 0.0
        if not np.isfinite(transformed).all():
            raise ValueError("non-finite transformed feature matrix")
        return transformed


def ordered_top3_design(frame, design: np.ndarray) -> list[np.ndarray]:
    if len(frame) != len(design):
        raise ValueError("feature frame/design row count mismatch")
    packed: list[np.ndarray] = []
    for race_id, race in frame.groupby("race_id", sort=True):
        top3 = race.sort_values(["finish_position", "horse_number"], kind="mergesort").head(3)
        if top3["finish_position"].astype(int).tolist() != [1, 2, 3]:
            raise ValueError(f"official Top3 is incomplete in {race_id}")
        ix = frame.index.get_indexer(top3.index)
        if len(ix) != 3 or (ix < 0).any():
            raise ValueError(f"Top3 design index lookup failed in {race_id}")
        packed.append(design[ix])
    return packed


def nll_gradient(beta: np.ndarray, races: Sequence[np.ndarray], ridge: float = RIDGE) -> tuple[float, np.ndarray]:
    coef = np.asarray(beta, dtype=float)
    if len(races) == 0:
        raise ValueError("empty conditional-order training set")
    loss = 0.0
    gradient = np.zeros_like(coef)
    for x in races:
        utilities = x @ coef
        logp = utilities[0] - logsumexp(utilities) + utilities[1] - logsumexp(utilities[1:])
        p_all = np.exp(utilities - logsumexp(utilities))
        p_last = np.exp(utilities[1:] - logsumexp(utilities[1:]))
        loss -= float(logp)
        gradient += p_all @ x - x[0]
        gradient += p_last @ x[1:] - x[1]
    loss = loss / len(races) + 0.5 * ridge * float(coef @ coef)
    gradient = gradient / len(races) + ridge * coef
    return float(loss), gradient


def fit_beta(races: Sequence[np.ndarray]) -> tuple[np.ndarray, dict]:
    initial = np.zeros(10, dtype=float)
    result = minimize(
        nll_gradient,
        initial,
        args=(races, RIDGE),
        method="L-BFGS-B",
        jac=True,
        options={"maxiter": 500, "ftol": 1e-12, "gtol": 1e-8},
    )
    beta = np.asarray(result.x, dtype=float)
    objective, gradient = nll_gradient(beta, races, RIDGE)
    gradient_inf = float(np.linalg.norm(gradient, ord=np.inf))
    if not result.success or not np.isfinite(beta).all() or not np.isfinite(objective) \
            or not np.isfinite(gradient).all() or gradient_inf > 1e-6:
        raise RuntimeError(
            f"H1 L-BFGS-B acceptance failed: success={result.success}, "
            f"objective={objective}, gradient_inf={gradient_inf}, message={result.message}"
        )
    return beta, {
        "success": bool(result.success),
        "message": str(result.message),
        "iterations": int(result.nit),
        "function_evaluations": int(result.nfev),
        "objective": objective,
        "gradient_inf_norm": gradient_inf,
        "ridge_lambda": RIDGE,
        "initial_beta_zero": True,
    }


def temperature_objective(log_temperature: np.ndarray, races: Sequence[np.ndarray], beta: np.ndarray) -> tuple[float, np.ndarray]:
    log_t = float(np.asarray(log_temperature, dtype=float).reshape(-1)[0])
    scale = float(np.exp(-log_t))
    if not np.isfinite(scale) or scale <= 0.0:
        return float("inf"), np.asarray([float("nan")])
    loss = 0.0
    grad_log_t = 0.0
    for x in races:
        base = x @ beta
        utilities = scale * base
        p_all = np.exp(utilities - logsumexp(utilities))
        p_last = np.exp(utilities[1:] - logsumexp(utilities[1:]))
        grad_utility = p_all - np.asarray([1.0, 0.0, 0.0])
        grad_utility[1:] += p_last - np.asarray([1.0, 0.0])
        logp = utilities[0] - logsumexp(utilities) + utilities[1] - logsumexp(utilities[1:])
        loss -= float(logp)
        # d(utility)/d(log T) = -utility.
        grad_log_t -= float(grad_utility @ utilities)
    return loss / len(races), np.asarray([grad_log_t / len(races)], dtype=float)


def fit_temperature(races: Sequence[np.ndarray], beta: np.ndarray) -> tuple[float, dict]:
    if not races:
        raise ValueError("empty H2 conditional-order calibration set")
    low, high = TEMPERATURE_BOUNDS
    result = minimize(
        temperature_objective,
        np.asarray([0.0]),
        args=(races, beta),
        method="L-BFGS-B",
        jac=True,
        bounds=[(float(np.log(low)), float(np.log(high)))],
        options={"maxiter": 500, "ftol": 1e-12, "gtol": 1e-8},
    )
    log_t = float(result.x[0])
    temperature = float(np.exp(log_t))
    objective, gradient = temperature_objective(np.asarray([log_t]), races, beta)
    raw_grad = float(gradient[0])
    projected = raw_grad
    if log_t <= np.log(low) + 1e-8:
        projected = min(raw_grad, 0.0)
    elif log_t >= np.log(high) - 1e-8:
        projected = max(raw_grad, 0.0)
    projected_inf = abs(projected)
    if not result.success or not np.isfinite(temperature) or not np.isfinite(objective) \
            or not np.isfinite(raw_grad) or not (low <= temperature <= high) or projected_inf > 1e-6:
        raise RuntimeError(
            f"H2 temperature L-BFGS-B acceptance failed: success={result.success}, "
            f"T={temperature}, objective={objective}, projected_gradient_inf={projected_inf}, "
            f"message={result.message}"
        )
    return temperature, {
        "success": bool(result.success),
        "message": str(result.message),
        "iterations": int(result.nit),
        "function_evaluations": int(result.nfev),
        "objective": objective,
        "gradient_log_temperature": raw_grad,
        "projected_gradient_inf_norm": projected_inf,
        "temperature": temperature,
        "parameterization": "log_temperature",
        "bounds": [low, high],
        "initial_temperature": 1.0,
    }


def order_probabilities(utilities: np.ndarray) -> np.ndarray:
    values = np.asarray(utilities, dtype=float)
    if values.shape != (3,) or not np.isfinite(values).all():
        raise ValueError("conditional PL expects three finite utilities")
    probabilities = np.empty(6, dtype=float)
    for index, order in enumerate(PL_ORDERS):
        remaining = [0, 1, 2]
        probability = 1.0
        for chosen in order[:2]:
            logits = values[remaining]
            probability *= float(np.exp(values[chosen] - logsumexp(logits)))
            remaining.remove(chosen)
        probabilities[index] = probability
    if not np.isfinite(probabilities).all() or not np.isclose(probabilities.sum(), 1.0, rtol=0, atol=1e-12):
        raise RuntimeError("conditional PL order probabilities fail six-way normalization")
    return probabilities


def softmax(values: np.ndarray) -> np.ndarray:
    logits = np.asarray(values, dtype=float)
    return np.exp(logits - logsumexp(logits))
