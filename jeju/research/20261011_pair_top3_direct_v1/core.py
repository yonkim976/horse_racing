"""Locked symmetric feature and objective code for the direct pair study.

The module defines the single prespecified model. Importing it does not fit a
model or evaluate outcomes; callers must obtain the separate fit approval
before invoking either optimizer wrapper.
"""

from __future__ import annotations

import itertools
import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np
from scipy.special import expit, logit


LAMBDA = 1.0
H1_MAXITER = 500
H1_FTOL = 1e-12
H1_GTOL = 1e-8
ACCEPT_GRAD_INF = 1e-6
PLATT_BOUNDS = ((-20.0, 20.0), (0.05, 20.0))
PLATT_INIT = (0.0, 1.0)

MEAN_COLUMNS = (
    "hist_s1f_relpos_mean5",
    "hist_s1f_to_c4_forward_mean5",
    "hist_c4_to_g1f_forward_mean5",
)
COUNT_COLUMNS = (
    "hist_s1f_relpos_n",
    "hist_s1f_to_c4_pair_n",
    "hist_c4_to_g1f_pair_n",
)
RUNNER_COLUMNS = (
    "score",
    "hist_s1f_relpos_mean5",
    "hist_s1f_relpos_n",
    "hist_s1f_to_c4_forward_mean5",
    "hist_s1f_to_c4_pair_n",
    "hist_c4_to_g1f_forward_mean5",
    "hist_c4_to_g1f_pair_n",
)
BASIS_NAMES = tuple(
    name
    for column in RUNNER_COLUMNS
    for name in (f"sum:{column}", f"absdiff:{column}")
) + tuple(
    name
    for column in MEAN_COLUMNS
    for name in (f"missing_sum:{column}", f"missing_product:{column}")
)
assert len(RUNNER_COLUMNS) == 7 and len(BASIS_NAMES) == 20


class ModelContractError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ModelContractError(message)


@dataclass(frozen=True)
class Standardization:
    columns: tuple[str, ...]
    mean: np.ndarray
    scale: np.ndarray
    degenerate: tuple[bool, ...]
    support_weight: tuple[float, ...]


def _race_equal_runner_weights(race_ids: Sequence[object]) -> np.ndarray:
    ids = np.asarray(race_ids)
    require(ids.ndim == 1 and len(ids) > 0, "empty race-id vector")
    unique, inverse, counts = np.unique(ids, return_inverse=True, return_counts=True)
    require(len(unique) > 0, "empty race cohort")
    return 1.0 / (len(unique) * counts[inverse])


def fit_runner_standardization(
    h1_rows,
    race_ids: Sequence[object],
) -> Standardization:
    """Fit runner-level centering/scaling using only H1 and race-equal weights."""
    require(len(h1_rows) == len(race_ids), "H1 runner/race-id length mismatch")
    require(len(h1_rows) > 0, "cannot standardize an empty H1 cohort")
    weights = _race_equal_runner_weights(race_ids)
    means = np.empty(len(RUNNER_COLUMNS), dtype=float)
    scales = np.empty(len(RUNNER_COLUMNS), dtype=float)
    degenerate: list[bool] = []
    support_weights: list[float] = []

    for index, column in enumerate(RUNNER_COLUMNS):
        values = np.asarray(h1_rows[column], dtype=float)
        valid = np.isfinite(values)
        if column not in MEAN_COLUMNS:
            require(valid.all(), f"non-finite H1 runner input: {column}")
        usable_weight = weights[valid]
        usable_values = values[valid]
        total_weight = float(usable_weight.sum())
        require(total_weight > 0.0, f"no H1 support for runner input: {column}")
        mean = float(np.dot(usable_weight, usable_values) / total_weight)
        variance = float(np.dot(usable_weight, (usable_values - mean) ** 2) / total_weight)
        require(math.isfinite(mean) and math.isfinite(variance) and variance >= 0.0, f"invalid H1 moments for {column}")
        scale = math.sqrt(variance)
        is_degenerate = scale <= 1e-12
        means[index] = mean
        scales[index] = 1.0 if is_degenerate else scale
        degenerate.append(is_degenerate)
        support_weights.append(total_weight)

    return Standardization(
        columns=RUNNER_COLUMNS,
        mean=means,
        scale=scales,
        degenerate=tuple(degenerate),
        support_weight=tuple(support_weights),
    )


def transform_runners(rows, stats: Standardization) -> tuple[np.ndarray, np.ndarray]:
    """Apply H1 moments; missing means become standardized zero plus a mask."""
    require(stats.columns == RUNNER_COLUMNS, "runner standardization column order mismatch")
    n = len(rows)
    z = np.empty((n, len(RUNNER_COLUMNS)), dtype=float)
    missing_means = np.zeros((n, len(MEAN_COLUMNS)), dtype=float)
    for j, column in enumerate(RUNNER_COLUMNS):
        values = np.asarray(rows[column], dtype=float)
        valid = np.isfinite(values)
        if column in MEAN_COLUMNS:
            missing_means[:, MEAN_COLUMNS.index(column)] = (~valid).astype(float)
            centered = np.zeros(n, dtype=float)
            centered[valid] = (values[valid] - stats.mean[j]) / stats.scale[j]
            z[:, j] = 0.0 if stats.degenerate[j] else centered
        else:
            require(valid.all(), f"non-finite runner input during transform: {column}")
            z[:, j] = 0.0 if stats.degenerate[j] else (values - stats.mean[j]) / stats.scale[j]
    require(np.isfinite(z).all(), "non-finite standardized runner matrix")
    return z, missing_means


@dataclass(frozen=True)
class PairStandardization:
    mean: np.ndarray
    scale: np.ndarray
    degenerate: tuple[bool, ...]
    support_weight: tuple[float, ...]


@dataclass(frozen=True)
class PairData:
    race_ids: np.ndarray
    horse_numbers: np.ndarray
    basis: np.ndarray
    labels: np.ndarray
    p0: np.ndarray
    pair_weights: np.ndarray


def pair_basis(z_i: np.ndarray, z_j: np.ndarray, missing_i: np.ndarray, missing_j: np.ndarray) -> np.ndarray:
    """Construct the frozen 20-term symmetric basis for one unordered pair."""
    a = np.asarray(z_i, dtype=float)
    b = np.asarray(z_j, dtype=float)
    ma = np.asarray(missing_i, dtype=float)
    mb = np.asarray(missing_j, dtype=float)
    require(a.shape == b.shape == (7,), "runner basis vectors must have length seven")
    require(ma.shape == mb.shape == (3,), "missingness masks must have length three")
    feature_values: list[float] = []
    for left, right in zip(a, b, strict=True):
        feature_values.extend((float(left + right), float(abs(left - right))))
    for left, right in zip(ma, mb, strict=True):
        feature_values.extend((float(left + right), float(left * right)))
    vector = np.asarray(feature_values, dtype=float)
    require(vector.shape == (20,) and np.isfinite(vector).all(), "invalid symmetric pair basis")
    return vector


def enumerate_race_pairs(
    rows,
    z: np.ndarray,
    missing_means: np.ndarray,
    p0_by_pair: dict[tuple[int, int], float],
) -> tuple[list[tuple[int, int]], np.ndarray, np.ndarray, np.ndarray]:
    """Enumerate every C(N,2) pair in numeric order without using outcomes for selection."""
    require(len(rows) == len(z) == len(missing_means), "race runner/basis row count mismatch")
    ordered = rows.reset_index(drop=True).copy()
    order = np.argsort(ordered["horse_number"].to_numpy(dtype=int), kind="stable")
    ordered = ordered.iloc[order].reset_index(drop=True)
    z = np.asarray(z, dtype=float)[order]
    missing_means = np.asarray(missing_means, dtype=float)[order]
    numbers = ordered["horse_number"].to_numpy(dtype=int)
    require(len(numbers) >= 4 and len(set(numbers.tolist())) == len(numbers), "invalid pair roster")
    pairs = list(itertools.combinations(numbers.tolist(), 2))
    require(len(pairs) == math.comb(len(numbers), 2), "pair enumeration count mismatch")

    position_by_number = {int(number): position for position, number in enumerate(numbers)}
    basis = np.vstack([
        pair_basis(
            z[position_by_number[a]],
            z[position_by_number[b]],
            missing_means[position_by_number[a]],
            missing_means[position_by_number[b]],
        )
        for a, b in pairs
    ])
    p0 = np.asarray([float(p0_by_pair[pair]) for pair in pairs], dtype=float)
    require(np.isfinite(p0).all() and ((p0 > 0.0) & (p0 < 1.0)).all(), "pair prior outside (0,1)")

    finish = {int(row.horse_number): int(row.finish_position) for row in ordered.itertuples(index=False)}
    labels = np.asarray([float(finish[a] <= 3 and finish[b] <= 3) for a, b in pairs], dtype=float)
    require(int(labels.sum()) == 3, "race must have exactly three positive unordered pairs")
    pair_weight = np.full(len(pairs), 1.0 / len(pairs), dtype=float)
    return pairs, basis, labels, p0


def fit_pair_standardization(
    h1_race_bases: Sequence[np.ndarray],
) -> PairStandardization:
    """Fit pair-basis standardization with each H1 race having total weight one."""
    require(len(h1_race_bases) > 0, "empty H1 pair-basis cohort")
    arrays = [np.asarray(x, dtype=float) for x in h1_race_bases]
    require(all(a.ndim == 2 and a.shape[1] == 20 and len(a) > 0 for a in arrays), "invalid per-race pair-basis shape")
    require(all(np.isfinite(a).all() for a in arrays), "non-finite H1 pair basis")
    race_means = np.vstack([a.mean(axis=0) for a in arrays])
    mean = race_means.mean(axis=0)
    variance = np.vstack([((a - mean) ** 2).mean(axis=0) for a in arrays]).mean(axis=0)
    scale = np.sqrt(np.maximum(variance, 0.0))
    degenerate = scale <= 1e-12
    support = np.full(20, float(len(arrays)), dtype=float)
    scale[degenerate] = 1.0
    mean[degenerate] = 0.0
    return PairStandardization(mean, scale, tuple(bool(x) for x in degenerate), tuple(support.tolist()))


def transform_pair_basis(basis: np.ndarray, stats: PairStandardization) -> np.ndarray:
    array = np.asarray(basis, dtype=float)
    require(array.ndim == 2 and array.shape[1] == 20, "pair basis must have shape (n,20)")
    require(np.isfinite(array).all(), "non-finite unscaled pair basis")
    result = (array - stats.mean) / stats.scale
    for j, is_degenerate in enumerate(stats.degenerate):
        if is_degenerate:
            result[:, j] = 0.0
    require(np.isfinite(result).all(), "non-finite standardized pair basis")
    return result


def q0_from_scores(horse_numbers: Sequence[int], scores: Sequence[float]) -> tuple[dict[tuple[int, int], float], dict[tuple[int, int, int], float]]:
    """Return exact-Top3 tau=1 q0 and pair marginals with frozen fsum order."""
    require(len(horse_numbers) == len(scores) and len(horse_numbers) >= 4, "invalid q0 roster")
    rows = sorted(((int(n), float(s)) for n, s in zip(horse_numbers, scores, strict=True)), key=lambda item: item[0])
    numbers = [n for n, _ in rows]
    values = [s for _, s in rows]
    require(len(set(numbers)) == len(numbers), "duplicate q0 horse number")
    require(np.isfinite(np.asarray(values, dtype=float)).all(), "non-finite q0 score")
    triples = list(itertools.combinations(numbers, 3))
    energies = [math.fsum(values[numbers.index(h)] for h in triple) for triple in triples]
    require(all(math.isfinite(x) for x in energies), "non-finite q0 energy")
    max_energy = max(energies)
    weights = [math.exp(energy - max_energy) for energy in energies]
    normalizer = math.fsum(weights)
    require(math.isfinite(normalizer) and normalizer > 0.0, "invalid q0 normalizer")
    q = {triple: weight / normalizer for triple, weight in zip(triples, weights, strict=True)}
    pair_terms: dict[tuple[int, int], list[float]] = defaultdict(list)
    for triple in triples:
        for pair in itertools.combinations(triple, 2):
            pair_terms[pair].append(q[triple])
    pair_marginals = {pair: math.fsum(terms) for pair, terms in pair_terms.items()}
    require(len(pair_marginals) == math.comb(len(numbers), 2), "q0 pair coverage mismatch")
    require(all(math.isfinite(p) and 0.0 < p < 1.0 for p in pair_marginals.values()), "q0 pair marginal outside (0,1)")
    return pair_marginals, q


def pair_choice_from_logits(pairs: Sequence[tuple[int, int]], logits: Sequence[float]) -> tuple[int, int]:
    require(len(pairs) == len(logits) and len(pairs) > 0, "pair/logit length mismatch")
    values = np.asarray(logits, dtype=float)
    require(np.isfinite(values).all(), "non-finite pair logits")
    maximum = float(np.max(values))
    return min(canonical for canonical, value in zip((tuple(sorted(p)) for p in pairs), values, strict=True) if float(value) == maximum)


def _race_pair_weights(race_ids: Sequence[object]) -> np.ndarray:
    ids = np.asarray(race_ids)
    require(ids.ndim == 1 and len(ids) > 0, "empty pair race-id vector")
    unique, inverse, counts = np.unique(ids, return_inverse=True, return_counts=True)
    return 1.0 / (len(unique) * counts[inverse])


def h1_loss_gradient(beta: np.ndarray, basis: np.ndarray, p0: np.ndarray, labels: np.ndarray, race_ids: Sequence[object]) -> tuple[float, np.ndarray]:
    """Race-equal direct pair BCE plus fixed unit ridge and its analytic gradient."""
    x = np.asarray(basis, dtype=float)
    prior = np.asarray(p0, dtype=float)
    y = np.asarray(labels, dtype=float)
    coefficients = np.asarray(beta, dtype=float)
    require(x.ndim == 2 and x.shape[1] == 20, "H1 design must have shape (n,20)")
    require(len(x) == len(prior) == len(y) == len(race_ids), "H1 pair input lengths differ")
    require(coefficients.shape == (20,), "H1 coefficient vector must have length 20")
    require(np.isfinite(x).all() and np.isfinite(prior).all() and np.isfinite(y).all() and np.isfinite(coefficients).all(), "non-finite H1 objective input")
    require(((prior > 0.0) & (prior < 1.0)).all(), "H1 prior outside (0,1)")
    require(((y == 0.0) | (y == 1.0)).all(), "H1 labels are not binary")
    weights = _race_pair_weights(race_ids)
    logits = logit(prior) + x @ coefficients
    require(np.isfinite(logits).all(), "non-finite H1 logits")
    # logaddexp is stable for large-magnitude logits.
    losses = np.logaddexp(0.0, logits) - y * logits
    loss = float(np.dot(weights, losses) + 0.5 * np.dot(coefficients, coefficients))
    residual = weights * (expit(logits) - y)
    gradient = x.T @ residual + coefficients
    require(math.isfinite(loss) and np.isfinite(gradient).all(), "non-finite H1 objective/gradient")
    return loss, gradient


def fit_h1(beta0: np.ndarray, basis: np.ndarray, p0: np.ndarray, labels: np.ndarray, race_ids: Sequence[object]):
    """Run the one prespecified H1 L-BFGS-B optimization; do not retry on failure."""
    from scipy.optimize import minimize

    start = np.asarray(beta0, dtype=float)
    require(np.array_equal(start, np.zeros(20, dtype=float)), "H1 start must be all-zero coefficients")
    result = minimize(
        fun=lambda b: h1_loss_gradient(b, basis, p0, labels, race_ids),
        x0=start,
        method="L-BFGS-B",
        jac=True,
        options={"maxiter": H1_MAXITER, "ftol": H1_FTOL, "gtol": H1_GTOL},
    )
    require(bool(result.success), f"H1 optimizer failed: {result.message}")
    require(np.isfinite(result.x).all() and math.isfinite(float(result.fun)) and np.isfinite(result.jac).all(), "H1 optimizer returned non-finite values")
    require(float(np.max(np.abs(result.jac))) <= ACCEPT_GRAD_INF, f"H1 stationarity check failed: {np.max(np.abs(result.jac))}")
    return result


def platt_loss_gradient(params: np.ndarray, raw_logits: np.ndarray, labels: np.ndarray, race_ids: Sequence[object]) -> tuple[float, np.ndarray]:
    """Race-equal H2 Platt BCE and analytic gradient, without extra regularization."""
    theta = np.asarray(params, dtype=float)
    logits_in = np.asarray(raw_logits, dtype=float)
    y = np.asarray(labels, dtype=float)
    require(theta.shape == (2,), "Platt parameter vector must be (A,B)")
    require(len(logits_in) == len(y) == len(race_ids), "Platt input lengths differ")
    require(np.isfinite(theta).all() and np.isfinite(logits_in).all() and np.isfinite(y).all(), "non-finite Platt input")
    require(((y == 0.0) | (y == 1.0)).all(), "Platt labels are not binary")
    weights = _race_pair_weights(race_ids)
    logits = theta[0] + theta[1] * logits_in
    losses = np.logaddexp(0.0, logits) - y * logits
    residual = weights * (expit(logits) - y)
    loss = float(np.dot(weights, losses))
    gradient = np.asarray([residual.sum(), np.dot(residual, logits_in)], dtype=float)
    require(math.isfinite(loss) and np.isfinite(gradient).all(), "non-finite Platt objective/gradient")
    return loss, gradient


def projected_gradient(params: Sequence[float], gradient: Sequence[float], bounds=PLATT_BOUNDS) -> np.ndarray:
    """Projected gradient for minimization under closed box bounds."""
    theta = np.asarray(params, dtype=float)
    grad = np.asarray(gradient, dtype=float)
    require(theta.shape == grad.shape == (len(bounds),), "projected-gradient input shape mismatch")
    result = grad.copy()
    for index, (lower, upper) in enumerate(bounds):
        if theta[index] == lower and grad[index] >= 0.0:
            result[index] = 0.0
        elif theta[index] == upper and grad[index] <= 0.0:
            result[index] = 0.0
    return result


def fit_platt(raw_logits: np.ndarray, labels: np.ndarray, race_ids: Sequence[object]):
    """Run exactly one bounded H2 Platt fit and enforce the frozen stationarity check."""
    from scipy.optimize import minimize

    result = minimize(
        fun=lambda theta: platt_loss_gradient(theta, raw_logits, labels, race_ids),
        x0=np.asarray(PLATT_INIT, dtype=float),
        method="L-BFGS-B",
        jac=True,
        bounds=PLATT_BOUNDS,
        options={"maxiter": H1_MAXITER, "ftol": H1_FTOL, "gtol": H1_GTOL},
    )
    require(bool(result.success), f"Platt optimizer failed: {result.message}")
    require(np.isfinite(result.x).all() and math.isfinite(float(result.fun)) and np.isfinite(result.jac).all(), "Platt optimizer returned non-finite values")
    for value, (lower, upper) in zip(result.x, PLATT_BOUNDS, strict=True):
        require(lower <= float(value) <= upper, "Platt optimizer violated bounds")
    pg = projected_gradient(result.x, result.jac)
    require(float(np.max(np.abs(pg))) <= ACCEPT_GRAD_INF, f"Platt stationarity check failed: {pg}")
    result.projected_gradient = pg
    result.active_bounds = tuple(
        "lower" if value == lower else "upper" if value == upper else "interior"
        for value, (lower, upper) in zip(result.x, PLATT_BOUNDS, strict=True)
    )
    return result
