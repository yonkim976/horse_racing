"""Pure probability helpers for the 20261022 Thoroughbred comparison.

All runner indices follow the row order supplied for a single race. Outcomes
are runner-aligned finishing-rank vectors: exactly one runner must have each
rank 1, 2, and 3. Other runners may have rank 0, a rank above 3, or NaN.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from functools import lru_cache
from itertools import combinations, permutations
from math import comb

import numpy as np
from scipy.optimize import minimize, minimize_scalar
from scipy.special import logsumexp
from scipy.stats import rankdata

_N_FEATURES = 3
_TOL = 1e-10
_ORDER_INDEX = np.asarray(list(permutations(range(3))), dtype=np.int64)
_ORDER_INDEX.setflags(write=False)


def _field_scores(scores: Sequence[float]) -> np.ndarray:
    values = np.asarray(scores, dtype=float)
    if values.ndim != 1:
        raise ValueError("scores must be a one-dimensional runner vector")
    if not np.isfinite(values).all():
        raise ValueError("scores must be finite")
    return values


def _positive_scalar(value: float, name: str) -> float:
    scalar = float(value)
    if not np.isfinite(scalar) or scalar <= 0:
        raise ValueError(f"{name} must be finite and greater than zero")
    return scalar


def _outcome_order(outcome: Sequence[float], n: int) -> tuple[int, int, int]:
    """Return indices of unique ranks 1, 2, 3; reject ties or missing ranks."""
    try:
        values = np.asarray(outcome, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError("outcome must be a runner-aligned rank vector") from exc
    if values.ndim != 1 or len(values) != n:
        raise ValueError("outcome must have one rank per runner")
    selected: list[int] = []
    for rank in (1, 2, 3):
        indices = np.flatnonzero(values == rank)
        if len(indices) != 1:
            raise ValueError(f"outcome must contain exactly one rank {rank}")
        selected.append(int(indices[0]))
    return tuple(selected)  # type: ignore[return-value]


@lru_cache(maxsize=32)
def _cached_support(n: int) -> tuple[np.ndarray, np.ndarray]:
    triples = np.asarray(list(combinations(range(n), 3)), dtype=np.int64).reshape(-1, 3)
    pairs = np.asarray(list(combinations(range(n), 2)), dtype=np.int64).reshape(-1, 2)
    triples.setflags(write=False)
    pairs.setflags(write=False)
    return triples, pairs


@lru_cache(maxsize=32)
def _cached_orders(n: int) -> np.ndarray:
    triples, _ = _cached_support(n)
    orders = triples[:, _ORDER_INDEX].reshape(-1, 3)
    orders.setflags(write=False)
    return orders


def support(n: int) -> tuple[np.ndarray, np.ndarray]:
    """Return cached, read-only unordered triple and pair supports."""
    if isinstance(n, (bool, np.bool_)) or not isinstance(n, (int, np.integer)):
        raise ValueError("n must be an integer")
    if n < 0:
        raise ValueError("n must be nonnegative")
    return _cached_support(int(n))


def trio_distribution(
    scores: Sequence[float],
    temp: float,
    pair_features: np.ndarray | None = None,
    beta: Sequence[float] | None = None,
) -> np.ndarray:
    """Return normalized probabilities for each unordered three-runner set.

    The set energy is ``sum(scores[T]) / temp + pair_features[T] @ beta``.
    Pair features have one row per lexicographically ordered triple and three
    fixed columns. With features but no beta, the pair contribution is zero.
    """
    values = _field_scores(scores)
    temperature = _positive_scalar(temp, "temp")
    triples, _ = support(len(values))
    if len(triples) == 0:
        raise ValueError("at least three runners are required")

    features = None
    if pair_features is not None:
        features = np.asarray(pair_features, dtype=float)
        if features.shape != (len(triples), _N_FEATURES):
            raise ValueError("pair_features must have shape (number of triples, 3)")
        if not np.isfinite(features).all():
            raise ValueError("pair_features must be finite")
    if beta is not None:
        coefficients = np.asarray(beta, dtype=float)
        if coefficients.shape != (_N_FEATURES,) or not np.isfinite(coefficients).all():
            raise ValueError("beta must contain three finite coefficients")
        if features is None:
            raise ValueError("pair_features are required when beta is supplied")
    else:
        coefficients = np.zeros(_N_FEATURES, dtype=float)

    energy = values[triples].sum(axis=1) / temperature
    if features is not None:
        energy = energy + features @ coefficients
    log_q = energy - logsumexp(energy)
    q = np.exp(log_q)
    # The normalization is exact up to floating point; reject an impossible
    # numerical failure instead of returning scores under a probability name.
    if not np.isfinite(q).all() or not np.isclose(q.sum(), 1.0, atol=_TOL, rtol=0):
        raise FloatingPointError("trio normalization failed")
    return q


def ordered_distribution(
    scores: Sequence[float], q: Sequence[float], order_temp: float
) -> tuple[np.ndarray, np.ndarray]:
    """Expand each trio probability over its six conditional PL orders."""
    values = _field_scores(scores)
    temperature = _positive_scalar(order_temp, "order_temp")
    triples, _ = support(len(values))
    if len(triples) == 0:
        raise ValueError("at least three runners are required")
    trio_prob = np.asarray(q, dtype=float)
    if trio_prob.ndim != 1 or len(trio_prob) != len(triples):
        raise ValueError("q must contain one probability per unordered triple")
    if not np.isfinite(trio_prob).all() or np.any(trio_prob < 0):
        raise ValueError("q must contain finite nonnegative probabilities")
    if not np.isclose(trio_prob.sum(), 1.0, atol=_TOL, rtol=0):
        raise ValueError("q must sum to one")

    orders = _cached_orders(len(values))
    utility = values / temperature
    order_utility = utility[orders]
    log_pl = (
        order_utility[:, 0]
        - logsumexp(order_utility, axis=1)
        + order_utility[:, 1]
        - np.logaddexp(order_utility[:, 1], order_utility[:, 2])
    )
    mass = np.repeat(trio_prob, 6) * np.exp(log_pl)
    if not np.isfinite(mass).all() or not np.isclose(mass.sum(), 1.0, atol=5e-10, rtol=0):
        raise FloatingPointError("ordered distribution normalization failed")
    return orders, mass


def marginals(n: int, orders: np.ndarray, mass: Sequence[float]) -> dict[str, np.ndarray]:
    """Sum a joint ordered-Top3 distribution into coherent betting marginals.

    ``quinella`` and ``qpl`` are symmetric matrices whose off-diagonal entries
    are the probability that the pair appears in Top2 or Top3, respectively.
    ``exacta[i, j]`` is the probability that i wins and j finishes second.
    """
    if isinstance(n, (bool, np.bool_)) or not isinstance(n, (int, np.integer)) or n < 3:
        raise ValueError("n must be an integer of at least three")
    n = int(n)
    raw_orders = np.asarray(orders)
    if raw_orders.ndim != 2 or raw_orders.shape[1] != 3:
        raise ValueError("orders must have shape (number of outcomes, 3)")
    if not np.issubdtype(raw_orders.dtype, np.number) or not np.isfinite(raw_orders).all():
        raise ValueError("orders must contain finite integer indices")
    if np.any(raw_orders != np.floor(raw_orders)):
        raise ValueError("orders must contain integer runner indices")
    order_array = raw_orders.astype(np.int64, copy=False)
    probabilities = np.asarray(mass, dtype=float)
    expected = comb(n, 3) * 6
    if len(order_array) != expected:
        raise ValueError("orders must contain every ordered triple exactly once")
    if probabilities.ndim != 1 or len(probabilities) != len(order_array):
        raise ValueError("mass must have one value per order")
    if not np.isfinite(probabilities).all() or np.any(probabilities < 0):
        raise ValueError("mass must contain finite nonnegative values")
    if not np.isclose(probabilities.sum(), 1.0, atol=5e-10, rtol=0):
        raise ValueError("mass must sum to one")
    if np.any(order_array < 0) or np.any(order_array >= n):
        raise ValueError("orders contain an out-of-range runner index")
    if np.any(np.diff(np.sort(order_array, axis=1), axis=1) == 0):
        raise ValueError("each order must contain three distinct runners")
    first, second, third = order_array.T
    encoded = (first * n + second) * n + third
    if np.unique(encoded).size != expected:
        raise ValueError("orders must contain every ordered triple exactly once")

    win = np.bincount(first, weights=probabilities, minlength=n)
    top2 = np.bincount(
        np.concatenate((first, second)),
        weights=np.concatenate((probabilities, probabilities)),
        minlength=n,
    )
    top3 = np.bincount(
        np.concatenate((first, second, third)),
        weights=np.tile(probabilities, 3),
        minlength=n,
    )
    quinella_ids = np.concatenate((first * n + second, second * n + first))
    quinella = np.bincount(
        quinella_ids,
        weights=np.tile(probabilities, 2),
        minlength=n * n,
    ).reshape(n, n)
    qpl_ids = np.concatenate(
        (
            first * n + second,
            second * n + first,
            first * n + third,
            third * n + first,
            second * n + third,
            third * n + second,
        )
    )
    qpl = np.bincount(
        qpl_ids,
        weights=np.tile(probabilities, 6),
        minlength=n * n,
    ).reshape(n, n)
    exacta = np.bincount(
        first * n + second,
        weights=probabilities,
        minlength=n * n,
    ).reshape(n, n)
    return {
        "win": win,
        "top2": top2,
        "top3": top3,
        "quinella": quinella,
        "qpl": qpl,
        "exacta": exacta,
    }


def _validated_races(
    races: Iterable[tuple[Sequence[float], Sequence[float]]],
) -> list[tuple[np.ndarray, tuple[int, int, int]]]:
    data: list[tuple[np.ndarray, tuple[int, int, int]]] = []
    for scores, outcome in races:
        values = _field_scores(scores)
        if len(values) < 3:
            raise ValueError("each race must have at least three runners")
        order = _outcome_order(outcome, len(values))
        data.append((values, order))
    if not data:
        raise ValueError("at least one race is required")
    return data


def fit_order_temperature(
    races: Iterable[tuple[Sequence[float], Sequence[float]]],
    bounds: tuple[float, float] = (0.35, 4.0),
) -> float:
    """Fit one temperature by equal-race conditional PL order NLL."""
    data = _validated_races(races)
    if len(bounds) != 2:
        raise ValueError("bounds must be a (lower, upper) pair")
    lower = _positive_scalar(bounds[0], "lower bound")
    upper = _positive_scalar(bounds[1], "upper bound")
    if lower >= upper:
        raise ValueError("temperature bounds must be increasing")

    ordered_scores = np.asarray(
        [[scores[horse] for horse in order] for scores, order in data], dtype=float
    )

    def objective(inverse_temp: float) -> float:
        utility = ordered_scores * inverse_temp
        log_probability = (
            utility[:, 0]
            - logsumexp(utility, axis=1)
            + utility[:, 1]
            - np.logaddexp(utility[:, 1], utility[:, 2])
        )
        return float(-np.mean(log_probability))

    # PL NLL is convex in inverse temperature. Optimize in that parameter,
    # then include both closed-interval endpoints in the comparison.
    inv_lo, inv_hi = 1.0 / upper, 1.0 / lower
    result = minimize_scalar(objective, bounds=(inv_lo, inv_hi), method="bounded")
    if not result.success or not np.isfinite(result.fun) or not np.isfinite(result.x):
        raise RuntimeError(f"order temperature optimization failed: {result.message}")
    candidates = [(float(result.fun), float(result.x))]
    candidates.extend((objective(value), value) for value in (inv_lo, inv_hi))
    _, inverse_temp = min(candidates, key=lambda item: item[0])
    return float(1.0 / inverse_temp)


def pair_features(frame) -> np.ndarray:
    """Build the fixed three-column trio features for one race DataFrame.

    The frame row order is the runner order. Missing front probabilities and
    missing pair histories contribute zero. Histories are ranked within the
    observed field using average ranks of negative sectional time, then mapped
    to [-1, 1] by ``2 * (rank - .5) / nobs - 1``.
    """
    required = (
        "front_gate_probability",
        "section_last600_mean3",
        "section_late_mean3",
    )
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"frame is missing required columns: {', '.join(missing)}")
    n = len(frame)
    triples, _ = support(n)
    try:
        front = frame[required[0]].to_numpy(dtype=float, na_value=np.nan)
        last600 = frame[required[1]].to_numpy(dtype=float, na_value=np.nan)
        late = frame[required[2]].to_numpy(dtype=float, na_value=np.nan)
    except (TypeError, ValueError) as exc:
        raise ValueError("pair feature columns must be numeric or missing") from exc

    if np.isinf(front).any() or np.isinf(last600).any() or np.isinf(late).any():
        raise ValueError("pair feature columns cannot contain infinite values")
    observed_front = np.isfinite(front)
    if np.any((front[observed_front] < 0) | (front[observed_front] > 1)):
        raise ValueError("front_gate_probability must be between zero and one")
    front = np.where(observed_front, front, 0.0)

    def centered_fast_rank(values: np.ndarray) -> np.ndarray:
        observed = np.isfinite(values)
        result = np.full(n, np.nan, dtype=float)
        count = int(observed.sum())
        if count:
            ranks = rankdata(-values[observed], method="average")
            result[observed] = 2.0 * (ranks - 0.5) / count - 1.0
        return result

    rank_last = centered_fast_rank(last600)
    rank_late = centered_fast_rank(late)
    left = triples[:, [0, 0, 1]]
    right = triples[:, [1, 2, 2]]
    front_pair = np.mean(front[left] * front[right], axis=1)

    def pairwise_minimum(rank: np.ndarray) -> np.ndarray:
        left_rank, right_rank = rank[left], rank[right]
        observed = np.isfinite(left_rank) & np.isfinite(right_rank)
        pair_values = np.where(observed, np.minimum(left_rank, right_rank), 0.0)
        return np.mean(pair_values, axis=1)

    return np.column_stack((front_pair, pairwise_minimum(rank_last), pairwise_minimum(rank_late)))


def fit_pair_beta(
    races: Iterable[
        tuple[Sequence[float], float, Sequence[float], np.ndarray]
    ],
    ridge: float = 0.01,
    bound: float = 2.0,
    maxiter: int = 100,
) -> tuple[np.ndarray, dict[str, float | int | bool | str]]:
    """Fit the three bounded pair coefficients on prior-year trio-set NLL.

    Each item is ``(scores, temp, outcome, X)`` where ``X`` has one three-
    feature row per unordered trio. The objective equally weights races and
    starts at beta=0. Only the supplied calibration races are used. Returns
    ``(beta, diagnostics)`` so callers can preserve convergence evidence.
    """
    if not np.isfinite(ridge) or ridge < 0:
        raise ValueError("ridge must be finite and nonnegative")
    if not np.isfinite(bound) or bound <= 0:
        raise ValueError("bound must be finite and greater than zero")
    if (
        isinstance(maxiter, (bool, np.bool_))
        or not isinstance(maxiter, (int, np.integer))
        or maxiter < 1
    ):
        raise ValueError("maxiter must be a positive integer")

    data = []
    for scores, temp, outcome, features in races:
        values = _field_scores(scores)
        if len(values) < 3:
            raise ValueError("each race must have at least three runners")
        temperature = _positive_scalar(temp, "temp")
        order = _outcome_order(outcome, len(values))
        triples, _ = support(len(values))
        x = np.asarray(features, dtype=float)
        if x.shape != (len(triples), _N_FEATURES):
            raise ValueError("each X must have shape (number of triples, 3)")
        if not np.isfinite(x).all():
            raise ValueError("each X must be finite")
        actual = tuple(sorted(order))
        target_index = next(i for i, triple in enumerate(triples) if tuple(triple) == actual)
        base = values[triples].sum(axis=1) / temperature
        data.append((base, x, target_index))
    if not data:
        raise ValueError("at least one race is required")

    def objective(beta: np.ndarray) -> tuple[float, np.ndarray]:
        loss = 0.0
        gradient = np.zeros(_N_FEATURES, dtype=float)
        for base, x, target_index in data:
            energy = base + x @ beta
            log_z = logsumexp(energy)
            q = np.exp(energy - log_z)
            loss += log_z - energy[target_index]
            gradient += q @ x - x[target_index]
        scale = 1.0 / len(data)
        loss = loss * scale + 0.5 * float(ridge) * float(beta @ beta)
        gradient = gradient * scale + float(ridge) * beta
        return float(loss), gradient

    result = minimize(
        objective,
        x0=np.zeros(_N_FEATURES, dtype=float),
        method="L-BFGS-B",
        jac=True,
        bounds=[(-float(bound), float(bound))] * _N_FEATURES,
        options={"maxiter": int(maxiter)},
    )
    if not np.isfinite(result.x).all() or not np.isfinite(result.fun):
        raise RuntimeError("pair coefficient optimization returned non-finite values")
    beta = np.asarray(result.x, dtype=float)
    diagnostics: dict[str, float | int | bool | str] = {
        "success": bool(result.success),
        "status": int(result.status),
        "message": str(result.message),
        "iterations": int(result.nit),
        "function_evaluations": int(result.nfev),
        "objective": float(result.fun),
        "gradient_norm": float(np.linalg.norm(result.jac)),
        "bound_hit": bool(np.any(np.isclose(np.abs(beta), float(bound), atol=1e-7, rtol=0))),
    }
    return beta, diagnostics
