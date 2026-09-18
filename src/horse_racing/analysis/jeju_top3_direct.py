"""Direct linear Plackett--Luce model for accepted ordered top-three outcomes.

The input rows are contiguous by race.  A race contributes one observation to
the objective, while every accepted order for that race is marginalized in the
likelihood.  All rows in a race are retained in each Plackett--Luce denominator;
this is important for starters that were later disqualified or did not finish.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from numbers import Integral

import numpy as np
from scipy.optimize import minimize
from scipy.special import logsumexp


def _validate_inputs(
    X: np.ndarray,
    group_sizes: Sequence[int] | np.ndarray,
    accepted_orders: Sequence[Iterable[Sequence[int]]],
) -> tuple[np.ndarray, np.ndarray, tuple[tuple[tuple[int, int, int], ...], ...]]:
    """Validate and normalize the contiguous race representation."""
    features = np.asarray(X, dtype=float)
    if features.ndim != 2:
        raise ValueError("X must be a two-dimensional entry matrix")
    if not np.all(np.isfinite(features)):
        raise ValueError("X must contain only finite values")

    sizes_raw = np.asarray(group_sizes)
    if sizes_raw.ndim != 1:
        raise ValueError("group_sizes must be one-dimensional")
    sizes: list[int] = []
    for raw_size in sizes_raw.tolist():
        if not isinstance(raw_size, Integral):
            raise ValueError("group_sizes must contain integers")
        size = int(raw_size)
        if size < 3:
            raise ValueError("each race must have at least three starters")
        sizes.append(size)
    sizes_array = np.asarray(sizes, dtype=int)
    if not sizes or int(sizes_array.sum()) != len(features):
        raise ValueError("group_sizes must sum to the number of rows in X")

    orders_by_race = list(accepted_orders)
    if len(orders_by_race) != len(sizes):
        raise ValueError("accepted_orders must contain one sequence per race")

    normalized: list[tuple[tuple[int, int, int], ...]] = []
    for race_index, (race_orders, race_size) in enumerate(zip(orders_by_race, sizes, strict=True)):
        unique_orders: list[tuple[int, int, int]] = []
        seen: set[tuple[int, int, int]] = set()
        for raw_order in race_orders:
            values = tuple(raw_order)
            if len(values) != 3 or not all(isinstance(value, Integral) for value in values):
                raise ValueError(
                    f"race {race_index}: every accepted order must be an integer triple"
                )
            order = tuple(int(value) for value in values)
            if len(set(order)) != 3 or any(value < 0 or value >= race_size for value in order):
                raise ValueError(f"race {race_index}: accepted order has invalid local indices")
            if order not in seen:
                seen.add(order)
                unique_orders.append(order)
        if not unique_orders:
            raise ValueError(f"race {race_index}: accepted_orders cannot be empty")
        normalized.append(tuple(unique_orders))
    return features, sizes_array, tuple(normalized)


def _prepare_layout(
    X: np.ndarray,
    group_sizes: np.ndarray,
    accepted_orders: tuple[tuple[tuple[int, int, int], ...], ...],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Build padded arrays once so optimizer evaluations stay vectorized."""
    n_races = len(group_sizes)
    max_starters = int(group_sizes.max())
    max_orders = max(len(orders) for orders in accepted_orders)
    padded_X = np.zeros((n_races, max_starters, X.shape[1]), dtype=float)
    row_mask = np.zeros((n_races, max_starters), dtype=bool)
    order_indices = np.zeros((n_races, max_orders, 3), dtype=int)
    order_mask = np.zeros((n_races, max_orders), dtype=bool)
    row_start = 0
    for race_index, (race_size, race_orders) in enumerate(
        zip(group_sizes, accepted_orders, strict=True)
    ):
        size = int(race_size)
        padded_X[race_index, :size] = X[row_start : row_start + size]
        row_mask[race_index, :size] = True
        order_indices[race_index, : len(race_orders)] = np.asarray(race_orders, dtype=int)
        order_mask[race_index, : len(race_orders)] = True
        row_start += size
    return padded_X, row_mask, order_indices, order_mask


def _loss_and_gradient_padded(
    coef: np.ndarray,
    padded_X: np.ndarray,
    row_mask: np.ndarray,
    order_indices: np.ndarray,
    order_mask: np.ndarray,
    l2: float,
) -> tuple[float, np.ndarray]:
    """Evaluate mean race NLL plus L2 and its exact coefficient gradient."""
    scores = np.einsum("rmf,f->rm", padded_X, coef, optimize=True)
    scores = np.where(row_mask, scores, -np.inf)
    log_denominator_all = logsumexp(scores, axis=1)
    probability_all = np.exp(scores - log_denominator_all[:, None])
    probability_all[~row_mask] = 0.0

    first = order_indices[:, :, 0]
    second = order_indices[:, :, 1]
    third = order_indices[:, :, 2]
    first_scores = np.take_along_axis(scores, first, axis=1)
    second_scores = np.take_along_axis(scores, second, axis=1)
    third_scores = np.take_along_axis(scores, third, axis=1)

    race_rows = np.arange(len(padded_X))[:, None]
    order_numbers = np.arange(order_indices.shape[1])[None, :]
    order_scores = np.broadcast_to(
        scores[:, None, :],
        (len(padded_X), order_indices.shape[1], padded_X.shape[1]),
    ).copy()
    order_scores[race_rows, order_numbers, first] = -np.inf
    log_denominator_after_first = logsumexp(order_scores, axis=2)
    probability_after_first = np.exp(order_scores - log_denominator_after_first[:, :, None])
    order_scores[race_rows, order_numbers, second] = -np.inf
    log_denominator_after_second = logsumexp(order_scores, axis=2)
    probability_after_second = np.exp(order_scores - log_denominator_after_second[:, :, None])
    probability_after_first[~np.isfinite(probability_after_first)] = 0.0
    probability_after_second[~np.isfinite(probability_after_second)] = 0.0
    log_order_probability = (
        first_scores
        - log_denominator_all[:, None]
        + second_scores
        - log_denominator_after_first
        + third_scores
        - log_denominator_after_second
    )
    log_order_probability = np.where(order_mask, log_order_probability, -np.inf)
    log_observed_probability = logsumexp(log_order_probability, axis=1)
    order_weights = np.exp(log_order_probability - log_observed_probability[:, None])
    order_weights[~order_mask] = 0.0

    # Conditional PL distributions after removing first and first+second.
    order_rows = np.broadcast_to(race_rows, order_weights.shape)
    weighted_p1 = (order_weights[:, :, None] * probability_after_first).sum(axis=1)
    weighted_p2 = (order_weights[:, :, None] * probability_after_second).sum(axis=1)
    score_gradient = probability_all + weighted_p1 + weighted_p2
    np.add.at(score_gradient, (order_rows, first), -order_weights)
    np.add.at(score_gradient, (order_rows, second), -order_weights)
    np.add.at(score_gradient, (order_rows, third), -order_weights)
    score_gradient[~row_mask] = 0.0

    n_races = len(padded_X)
    loss = -float(np.mean(log_observed_probability))
    gradient = np.einsum("rmf,rm->f", padded_X, score_gradient, optimize=True)
    gradient /= n_races
    if l2:
        loss += 0.5 * l2 * float(np.dot(coef, coef))
        gradient += l2 * coef
    return float(loss), gradient


def _loss_and_gradient(
    coef: np.ndarray,
    X: np.ndarray,
    group_sizes: np.ndarray,
    accepted_orders: tuple[tuple[tuple[int, int, int], ...], ...],
    l2: float,
) -> tuple[float, np.ndarray]:
    """Prepare a layout and evaluate the vectorized objective once."""
    layout = _prepare_layout(X, group_sizes, accepted_orders)
    return _loss_and_gradient_padded(coef, *layout, l2)


def top3_objective_and_gradient(
    coef: np.ndarray,
    X: np.ndarray,
    group_sizes: Sequence[int] | np.ndarray,
    accepted_orders: Sequence[Iterable[Sequence[int]]],
    *,
    l2: float = 0.01,
) -> tuple[float, np.ndarray]:
    """Return the objective and analytic gradient for a coefficient vector.

    This public helper is useful for finite-difference checks and diagnostics;
    :class:`DirectTop3Linear` uses the same path during optimization.
    """
    if not np.isfinite(l2) or l2 < 0:
        raise ValueError("l2 must be finite and non-negative")
    features, sizes, orders = _validate_inputs(X, group_sizes, accepted_orders)
    weights = np.asarray(coef, dtype=float)
    if weights.ndim != 1 or len(weights) != features.shape[1]:
        raise ValueError("coef must be one-dimensional with one value per feature")
    if not np.all(np.isfinite(weights)):
        raise ValueError("coef must contain only finite values")
    return _loss_and_gradient(weights, features, sizes, orders, float(l2))


class DirectTop3Linear:
    """A deterministic L2-regularized linear score optimized by Top3 PL NLL."""

    def __init__(self, l2: float = 0.01, max_iter: int = 150) -> None:
        if not np.isfinite(l2) or l2 < 0:
            raise ValueError("l2 must be finite and non-negative")
        if not isinstance(max_iter, Integral) or int(max_iter) < 1:
            raise ValueError("max_iter must be a positive integer")
        self.l2 = float(l2)
        self.max_iter = int(max_iter)

    def fit(
        self,
        X: np.ndarray,
        group_sizes: Sequence[int] | np.ndarray,
        accepted_orders: Sequence[Iterable[Sequence[int]]],
    ) -> DirectTop3Linear:
        features, sizes, orders = _validate_inputs(X, group_sizes, accepted_orders)
        self.n_features_in_ = features.shape[1]
        initial = np.zeros(self.n_features_in_, dtype=float)
        layout = _prepare_layout(features, sizes, orders)

        def objective(weights: np.ndarray) -> tuple[float, np.ndarray]:
            return _loss_and_gradient_padded(weights, *layout, self.l2)

        result = minimize(
            objective,
            initial,
            method="L-BFGS-B",
            jac=True,
            options={"maxiter": self.max_iter, "ftol": 1e-12, "gtol": 1e-8, "maxls": 50},
        )
        self.coef_ = np.asarray(result.x, dtype=float)
        self.objective_ = float(result.fun)
        self.n_iter_ = int(getattr(result, "nit", 0))
        self.success_ = bool(result.success)
        self.message_ = str(result.message)
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        """Return one unnormalized latent score for each entry row."""
        if not hasattr(self, "coef_"):
            raise ValueError("DirectTop3Linear is not fitted")
        features = np.asarray(X, dtype=float)
        if features.ndim != 2:
            raise ValueError("X must be a two-dimensional entry matrix")
        if features.shape[1] != self.n_features_in_:
            raise ValueError("X has a different number of features than the fitted model")
        if not np.all(np.isfinite(features)):
            raise ValueError("X must contain only finite values")
        return features @ self.coef_

    @property
    def objective(self) -> float:
        if not hasattr(self, "objective_"):
            raise ValueError("DirectTop3Linear is not fitted")
        return self.objective_

    @property
    def n_iter(self) -> int:
        if not hasattr(self, "n_iter_"):
            raise ValueError("DirectTop3Linear is not fitted")
        return self.n_iter_

    @property
    def success(self) -> bool:
        if not hasattr(self, "success_"):
            raise ValueError("DirectTop3Linear is not fitted")
        return self.success_


__all__ = ["DirectTop3Linear", "top3_objective_and_gradient"]
