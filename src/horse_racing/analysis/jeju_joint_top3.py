"""A small coherent joint set/order model for accepted Jeju Top3 orders.

The model has one shared tanh layer and two heads.  The inclusion head defines
an exponential family over three-horse sets; the order head defines a
Plackett--Luce distribution conditional on a selected set.  Consequently the
probability of an ordered triple is a proper joint distribution, including in
the presence of podium ties.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterable
from dataclasses import dataclass
from numbers import Integral

import numpy as np
from scipy.optimize import minimize


class JointTop3Error(ValueError):
    """Raised when joint Top3 inputs violate the race contract."""


@dataclass(frozen=True)
class _Layout:
    group_sizes: np.ndarray
    race_starts: np.ndarray
    set_indices: np.ndarray
    set_owners: np.ndarray
    set_starts: np.ndarray
    set_ends: np.ndarray
    accepted_set_indices: np.ndarray
    accepted_set_owners: np.ndarray
    accepted_set_starts: np.ndarray
    accepted_set_ends: np.ndarray
    order_indices: np.ndarray
    order_set_indices: np.ndarray
    order_owners: np.ndarray
    accepted_order_indices: np.ndarray
    accepted_order_set_indices: np.ndarray
    accepted_order_owners: np.ndarray
    accepted_order_starts: np.ndarray
    accepted_order_ends: np.ndarray

    @property
    def n_races(self) -> int:
        return int(self.group_sizes.size)


_PERMUTATIONS = np.asarray(list(itertools.permutations(range(3))), dtype=np.int64)


def _as_group_sizes(group_sizes: Iterable[int], n_rows: int) -> np.ndarray:
    values = np.asarray(list(group_sizes), dtype=np.int64)
    if values.ndim != 1 or values.size == 0 or np.any(values < 3):
        raise JointTop3Error("group_sizes must contain race sizes of at least three")
    if int(values.sum()) != n_rows:
        raise JointTop3Error("group_sizes must sum to the number of rows")
    return values


def _validate_orders(
    orders: Iterable[Iterable[Iterable[int]]], n_races: int
) -> list[list[tuple[int, int, int]]]:
    try:
        supplied = list(orders)
    except TypeError as exc:
        raise JointTop3Error("accepted_orders must contain one order list per race") from exc
    if len(supplied) != n_races:
        raise JointTop3Error("accepted_orders must align with group_sizes")
    result: list[list[tuple[int, int, int]]] = []
    for race_orders in supplied:
        try:
            rows = list(race_orders)
        except TypeError as exc:
            raise JointTop3Error("each race must have at least one accepted order") from exc
        if not rows:
            raise JointTop3Error("each race must have at least one accepted order")
        checked: list[tuple[int, int, int]] = []
        seen: set[tuple[int, int, int]] = set()
        for order in rows:
            try:
                values = tuple(order)
            except TypeError as exc:
                raise JointTop3Error("each accepted order must contain three indices") from exc
            if len(values) != 3 or any(
                isinstance(v, bool) or not isinstance(v, Integral) for v in values
            ):
                raise JointTop3Error("each accepted order must contain three integer indices")
            values = tuple(int(v) for v in values)
            if len(set(values)) != 3:
                raise JointTop3Error("accepted orders must contain distinct indices")
            if values in seen:
                raise JointTop3Error("accepted_orders must not contain duplicate orders")
            seen.add(values)
            checked.append(values)
        result.append(checked)
    return result


def build_layout(
    group_sizes: Iterable[int], accepted_orders: Iterable[Iterable[Iterable[int]]]
) -> _Layout:
    """Build the reusable padded/flat race layout used by the objective."""

    sizes = np.asarray(list(group_sizes), dtype=np.int64)
    if sizes.ndim != 1 or sizes.size == 0 or np.any(sizes < 3):
        raise JointTop3Error("group_sizes must contain race sizes of at least three")
    orders = _validate_orders(accepted_orders, int(sizes.size))
    race_starts = np.concatenate(([0], np.cumsum(sizes[:-1]))).astype(np.int64)

    sets: list[tuple[int, int, int]] = []
    owners: list[int] = []
    set_starts: list[int] = []
    set_ends: list[int] = []
    accepted_sets: list[int] = []
    accepted_set_owners: list[int] = []
    accepted_set_starts: list[int] = []
    accepted_set_ends: list[int] = []
    accepted_order_indices: list[tuple[int, int, int]] = []
    accepted_order_sets: list[int] = []
    accepted_order_owners: list[int] = []
    accepted_order_starts: list[int] = []
    accepted_order_ends: list[int] = []
    for race, (size, start, race_orders) in enumerate(zip(sizes, race_starts, orders, strict=True)):
        local_sets = list(itertools.combinations(range(int(size)), 3))
        lookup: dict[tuple[int, int, int], int] = {}
        set_starts.append(len(sets))
        for local in local_sets:
            lookup[local] = len(sets)
            sets.append(tuple(int(start) + i for i in local))
            owners.append(race)
        set_ends.append(len(sets))
        accepted_set_starts.append(len(accepted_sets))
        local_seen: set[int] = set()
        for order in race_orders:
            if any(index < 0 or index >= int(size) for index in order):
                raise JointTop3Error("accepted order index is outside its race")
            key = tuple(sorted(order))
            set_id = lookup[key]
            if set_id not in local_seen:
                local_seen.add(set_id)
                accepted_sets.append(set_id)
                accepted_set_owners.append(race)
            accepted_order_indices.append(tuple(int(start) + i for i in order))
            accepted_order_sets.append(set_id)
            accepted_order_owners.append(race)
        accepted_set_ends.append(len(accepted_sets))
        accepted_order_starts.append(len(accepted_order_indices) - len(race_orders))
        accepted_order_ends.append(len(accepted_order_indices))

    set_indices = np.asarray(sets, dtype=np.int64)
    set_owners = np.asarray(owners, dtype=np.int64)
    return _Layout(
        group_sizes=sizes,
        race_starts=race_starts,
        set_indices=set_indices,
        set_owners=set_owners,
        set_starts=np.asarray(set_starts, dtype=np.int64),
        set_ends=np.asarray(set_ends, dtype=np.int64),
        accepted_set_indices=np.asarray(accepted_sets, dtype=np.int64),
        accepted_set_owners=np.asarray(accepted_set_owners, dtype=np.int64),
        accepted_set_starts=np.asarray(accepted_set_starts, dtype=np.int64),
        accepted_set_ends=np.asarray(accepted_set_ends, dtype=np.int64),
        order_indices=np.empty((0, 3), dtype=np.int64),
        order_set_indices=np.empty(0, dtype=np.int64),
        order_owners=np.empty(0, dtype=np.int64),
        accepted_order_indices=np.asarray(accepted_order_indices, dtype=np.int64),
        accepted_order_set_indices=np.asarray(accepted_order_sets, dtype=np.int64),
        accepted_order_owners=np.asarray(accepted_order_owners, dtype=np.int64),
        accepted_order_starts=np.asarray(accepted_order_starts, dtype=np.int64),
        accepted_order_ends=np.asarray(accepted_order_ends, dtype=np.int64),
    )


def _validate_x(x: np.ndarray, n_features: int | None = None) -> np.ndarray:
    values = np.asarray(x, dtype=float)
    if values.ndim != 2 or (n_features is not None and values.shape[1] != n_features):
        raise JointTop3Error("X must be a two-dimensional numeric array")
    if not np.all(np.isfinite(values)):
        raise JointTop3Error("X must contain only finite values")
    return values


def _group_logsumexp(values: np.ndarray, starts: np.ndarray, ends: np.ndarray) -> np.ndarray:
    maximum = np.maximum.reduceat(values, starts)
    repeated = np.repeat(maximum, ends - starts)
    sums = np.add.reduceat(np.exp(values - repeated), starts)
    return maximum + np.log(sums)


def _row_logsumexp(values: np.ndarray) -> np.ndarray:
    maximum = np.max(values, axis=1)
    return maximum + np.log(np.sum(np.exp(values - maximum[:, None]), axis=1))


def _scatter_set(values: np.ndarray, indices: np.ndarray, n_rows: int) -> np.ndarray:
    result = np.zeros(n_rows, dtype=float)
    np.add.at(result, indices[:, 0], values)
    np.add.at(result, indices[:, 1], values)
    np.add.at(result, indices[:, 2], values)
    return result


def _scatter_order(values: np.ndarray, indices: np.ndarray, n_rows: int) -> np.ndarray:
    result = np.zeros(n_rows, dtype=float)
    np.add.at(result, indices[:, 0], values[:, 0])
    np.add.at(result, indices[:, 1], values[:, 1])
    np.add.at(result, indices[:, 2], values[:, 2])
    return result


def _score_loss_gradient(
    scores: np.ndarray,
    layout: _Layout,
    joint_weight: float,
    beta_set: float = 1.0,
    beta_order: float = 1.0,
) -> tuple[float, np.ndarray, float, float]:
    """Return loss, score gradient, set NLL, and joint-order NLL."""

    if scores.shape != (int(layout.group_sizes.sum()), 2):
        raise JointTop3Error("scores must have shape (sum(group_sizes), 2)")
    if not np.all(np.isfinite(scores)):
        raise JointTop3Error("scores must contain only finite values")
    if not 0.0 <= joint_weight <= 1.0:
        raise JointTop3Error("joint_weight must be between zero and one")
    if not np.isfinite(beta_set) or beta_set <= 0 or not np.isfinite(beta_order) or beta_order <= 0:
        raise JointTop3Error("score temperatures must be positive and finite")

    a = scores[:, 0] * beta_set
    b = scores[:, 1] * beta_order
    if not np.all(np.isfinite(a)) or not np.all(np.isfinite(b)):
        raise JointTop3Error("scaled scores must remain finite")
    set_logits = a[layout.set_indices].sum(axis=1)
    set_lse = _group_logsumexp(set_logits, layout.set_starts, layout.set_ends)
    set_prob = np.exp(set_logits - set_lse[layout.set_owners])
    accepted_set_logits = set_logits[layout.accepted_set_indices]
    accepted_set_lse = _group_logsumexp(
        accepted_set_logits, layout.accepted_set_starts, layout.accepted_set_ends
    )
    set_nll = float(np.mean(set_lse - accepted_set_lse))
    set_grad_logits = set_prob.copy()
    accepted_set_prob = np.exp(accepted_set_logits - accepted_set_lse[layout.accepted_set_owners])
    np.add.at(set_grad_logits, layout.accepted_set_indices, -accepted_set_prob)
    grad_a_scaled = _scatter_set(set_grad_logits, layout.set_indices, scores.shape[0])

    # The full-distribution expectation of the conditional PL score gradient
    # is zero for every selected set.  Only the accepted-order term is needed,
    # avoiding an expansion to six rows for every possible set.
    grad_b_scaled = np.zeros(scores.shape[0], dtype=float)

    accepted_order_scores = b[layout.accepted_order_indices]
    accepted_first_lse = _row_logsumexp(accepted_order_scores)
    accepted_second_lse = _row_logsumexp(accepted_order_scores[:, 1:])
    accepted_log_cond = (
        accepted_order_scores[:, 0]
        - accepted_first_lse
        + accepted_order_scores[:, 1]
        - accepted_second_lse
    )
    accepted_joint_log = (
        set_logits[layout.accepted_order_set_indices]
        - set_lse[layout.accepted_order_owners]
        + accepted_log_cond
    )
    accepted_joint_lse = _group_logsumexp(
        accepted_joint_log, layout.accepted_order_starts, layout.accepted_order_ends
    )
    joint_nll = float(np.mean(-accepted_joint_lse))
    joint_set_grad_logits = set_prob.copy()
    accepted_joint_prob = np.exp(
        accepted_joint_log - accepted_joint_lse[layout.accepted_order_owners]
    )
    np.add.at(
        joint_set_grad_logits,
        layout.accepted_order_set_indices,
        -accepted_joint_prob,
    )
    joint_grad_a_scaled = _scatter_set(joint_set_grad_logits, layout.set_indices, scores.shape[0])
    accepted_soft_first = np.exp(accepted_order_scores - accepted_first_lse[:, None])
    accepted_soft_second = np.exp(accepted_order_scores[:, 1:] - accepted_second_lse[:, None])
    accepted_order_grad = np.zeros_like(accepted_order_scores)
    accepted_order_grad[:, 0] += accepted_joint_prob
    accepted_order_grad[:, 1] += accepted_joint_prob
    accepted_order_grad -= accepted_joint_prob[:, None] * accepted_soft_first
    accepted_order_grad[:, 1:] -= accepted_joint_prob[:, None] * accepted_soft_second
    np.add.at(
        grad_b_scaled,
        layout.accepted_order_indices[:, 0],
        -accepted_order_grad[:, 0],
    )
    np.add.at(
        grad_b_scaled,
        layout.accepted_order_indices[:, 1],
        -accepted_order_grad[:, 1],
    )
    np.add.at(
        grad_b_scaled,
        layout.accepted_order_indices[:, 2],
        -accepted_order_grad[:, 2],
    )
    grad_a_set = grad_a_scaled * beta_set
    grad_a_joint = joint_grad_a_scaled * beta_set
    grad_b = grad_b_scaled * beta_order
    loss = (1.0 - joint_weight) * set_nll + joint_weight * joint_nll
    gradient = np.column_stack(
        ((1.0 - joint_weight) * grad_a_set + joint_weight * grad_a_joint, joint_weight * grad_b)
    )
    gradient /= layout.n_races
    return float(loss), gradient, set_nll, joint_nll


class JointTop3MLP:
    """Shared-hidden-layer joint set/order Top3 model."""

    def __init__(self, hidden_dim: int = 16, l2: float = 0.001, max_iter: int = 100):
        if isinstance(hidden_dim, bool) or not isinstance(hidden_dim, Integral) or hidden_dim < 1:
            raise ValueError("hidden_dim must be a positive integer")
        if not np.isfinite(l2) or l2 < 0 or max_iter < 1:
            raise ValueError("l2 must be nonnegative and max_iter positive")
        self.hidden_dim = int(hidden_dim)
        self.l2 = float(l2)
        self.max_iter = int(max_iter)

    def _unpack(self, theta: np.ndarray, n_features: int) -> tuple[np.ndarray, ...]:
        h = self.hidden_dim
        at = 0
        w = theta[at : at + h * n_features].reshape(h, n_features)
        at += h * n_features
        hidden_bias = theta[at : at + h]
        at += h
        wa = theta[at : at + h]
        at += h
        ba = theta[at]
        at += 1
        wb = theta[at : at + h]
        at += h
        bb = theta[at]
        return w, hidden_bias, wa, np.asarray([ba]), wb, np.asarray([bb])

    def _forward(
        self, x: np.ndarray, theta: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        w, hidden_bias, wa, ba, wb, bb = self._unpack(theta, x.shape[1])
        hidden = np.tanh(x @ w.T + hidden_bias)
        return hidden @ wa + ba[0], hidden @ wb + bb[0], hidden

    def _theta_gradient(
        self, x: np.ndarray, theta: np.ndarray, score_gradient: np.ndarray, hidden: np.ndarray
    ) -> np.ndarray:
        w, _hidden_bias, wa, _ba, wb, _bb = self._unpack(theta, x.shape[1])
        grad_a = score_gradient[:, 0]
        grad_b = score_gradient[:, 1]
        dz = (grad_a[:, None] * wa[None, :] + grad_b[:, None] * wb[None, :]) * (
            1.0 - hidden * hidden
        )
        return np.concatenate(
            [
                (dz.T @ x).ravel(),
                dz.sum(axis=0),
                hidden.T @ grad_a,
                np.asarray([grad_a.sum()]),
                hidden.T @ grad_b,
                np.asarray([grad_b.sum()]),
            ]
        )

    def prepare_layout(self, group_sizes, accepted_orders):
        return build_layout(group_sizes, accepted_orders)

    def _loss_gradient_theta(self, theta, x, layout, joint_weight, include_l2=True):
        a, b, hidden = self._forward(x, theta)
        scores = np.column_stack((a, b))
        loss, score_grad, set_nll, joint_nll = _score_loss_gradient(scores, layout, joint_weight)
        gradient = self._theta_gradient(x, theta, score_grad, hidden)
        if include_l2 and self.l2:
            loss += 0.5 * self.l2 * float(np.dot(theta, theta))
            gradient = gradient + self.l2 * theta
        return loss, gradient, set_nll, joint_nll

    def fit(self, X, group_sizes, accepted_orders, tune=None, seed=0, joint_weight=0.5):
        x = _validate_x(X)
        layout = build_layout(group_sizes, accepted_orders)
        if int(layout.group_sizes.sum()) != len(x):
            raise JointTop3Error("group_sizes must sum to X rows")
        if not 0.0 <= joint_weight <= 1.0:
            raise JointTop3Error("joint_weight must be between zero and one")
        if tune is not None:
            if not isinstance(tune, tuple) or len(tune) != 3:
                raise JointTop3Error("tune must be (X, group_sizes, accepted_orders)")
            tune_x = _validate_x(tune[0], x.shape[1])
            tune_layout = build_layout(tune[1], tune[2])
            if len(tune_x) != int(tune_layout.group_sizes.sum()):
                raise JointTop3Error("tune group_sizes must sum to tune X rows")
        else:
            tune_x = tune_layout = None
        rng = np.random.default_rng(seed)
        n_parameters = self.hidden_dim * x.shape[1] + 3 * self.hidden_dim + 2
        theta0 = rng.normal(0.0, 0.05, size=n_parameters)
        theta0[-1] = 0.0
        theta0[-self.hidden_dim - 1] = 0.0
        best_theta = theta0.copy()
        if tune_x is not None:
            best_tune = _score_loss_gradient(
                np.column_stack(self._forward(tune_x, theta0)[:2]),
                tune_layout,
                joint_weight,
            )[0]
        else:
            best_tune = float("inf")
        callback_iterations = 0
        best_iteration = 0

        def objective(theta):
            value, gradient, _set, _joint = self._loss_gradient_theta(
                theta, x, layout, joint_weight, include_l2=True
            )
            return value, gradient

        def callback(theta):
            nonlocal best_theta, best_tune, callback_iterations, best_iteration
            callback_iterations += 1
            if tune_x is None:
                return
            candidate = _score_loss_gradient(
                np.column_stack(self._forward(tune_x, theta)[:2]),
                tune_layout,
                joint_weight,
            )[0]
            if candidate < best_tune:
                best_tune = float(candidate)
                best_theta = theta.copy()
                best_iteration = callback_iterations

        result = minimize(
            objective,
            theta0,
            jac=True,
            method="L-BFGS-B",
            callback=callback if tune_x is not None else None,
            options={"maxiter": self.max_iter, "ftol": 1e-12, "gtol": 1e-7, "maxls": 30},
        )
        if tune_x is None:
            best_theta = result.x.copy()
            best_iteration = int(result.nit)
        else:
            final_tune = _score_loss_gradient(
                np.column_stack(self._forward(tune_x, result.x)[:2]),
                tune_layout,
                joint_weight,
            )[0]
            if final_tune < best_tune:
                best_theta = result.x.copy()
                best_tune = float(final_tune)
                best_iteration = int(result.nit)
        self.n_features_in_ = x.shape[1]
        self.theta_ = best_theta
        self.seed_ = int(seed)
        self.joint_weight_ = float(joint_weight)
        train_loss, _g, set_nll, joint_nll = self._loss_gradient_theta(
            best_theta, x, layout, joint_weight, include_l2=True
        )
        self.objective_ = float(train_loss)
        self.set_objective_ = float(set_nll)
        self.joint_objective_ = float(joint_nll)
        self.tune_objective_ = float(best_tune) if tune_x is not None else None
        self.n_iter_ = int(result.nit)
        self.callback_iterations_ = int(callback_iterations)
        self.selected_iteration_ = int(best_iteration)
        self.success_ = bool(result.success)
        self.message_ = str(result.message)
        self.converged_ = self.success_
        return self

    def predict(self, X) -> np.ndarray:
        if not hasattr(self, "theta_"):
            raise JointTop3Error("fit must be called before predict")
        x = _validate_x(X, self.n_features_in_)
        a, b, _hidden = self._forward(x, self.theta_)
        result = np.column_stack((a, b))
        if not np.all(np.isfinite(result)):
            raise JointTop3Error("model produced non-finite scores")
        return result

    def scores_loss_and_gradient(
        self,
        scores,
        layout,
        joint_weight=None,
        beta_set=1.0,
        beta_order=1.0,
    ):
        values = np.asarray(scores, dtype=float)
        if values.ndim != 2 or values.shape[1] != 2:
            raise JointTop3Error("scores must have shape (N, 2)")
        if not isinstance(layout, _Layout):
            raise JointTop3Error("layout must be created by prepare_layout")
        if values.shape[0] != int(layout.group_sizes.sum()):
            raise JointTop3Error("scores do not match the supplied layout")
        weight = (
            self.joint_weight_
            if joint_weight is None and hasattr(self, "joint_weight_")
            else joint_weight
        )
        if weight is None:
            weight = 0.5
        return _score_loss_gradient(
            values, layout, float(weight), float(beta_set), float(beta_order)
        )[:2]

    def loss(
        self, X, group_sizes, accepted_orders, joint_weight=None, beta_set=1.0, beta_order=1.0
    ):
        scores = self.predict(X)
        layout = build_layout(group_sizes, accepted_orders)
        value, _gradient = self.scores_loss_and_gradient(
            scores,
            layout,
            joint_weight=joint_weight,
            beta_set=beta_set,
            beta_order=beta_order,
        )
        return float(value)

    def calibration_objective(
        self, log_betas, scores, group_sizes, accepted_orders, joint_weight=None, layout=None
    ):
        logs = np.asarray(log_betas, dtype=float)
        if logs.shape != (2,) or not np.all(np.isfinite(logs)):
            raise JointTop3Error("log_betas must contain two finite values")
        values = np.asarray(scores, dtype=float)
        beta = np.exp(logs)
        if layout is None:
            layout = build_layout(group_sizes, accepted_orders)
        value, gradient = self.scores_loss_and_gradient(
            values,
            layout,
            joint_weight=joint_weight,
            beta_set=beta[0],
            beta_order=beta[1],
        )
        return float(value), np.asarray(
            [np.sum(gradient[:, 0] * values[:, 0]), np.sum(gradient[:, 1] * values[:, 1])]
        )


# Names kept short for runner code and backwards-compatible discovery.
JointTop3Model = JointTop3MLP
JointTop3Tanh = JointTop3MLP
