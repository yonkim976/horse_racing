"""Direct conditional podium-order likelihood, without an inclusion head.

Each race contributes equally. For boundary ties, average over the distinct
compatible official podium sets and sum compatible orders within each set.
Training uses all races, not only races whose predicted set happened to hit.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize
from scipy.special import logsumexp

from horse_racing.analysis.jeju_joint_top3 import _validate_orders


@dataclass(frozen=True)
class ConditionalLayout:
    n_rows: int
    indices: np.ndarray
    starts: np.ndarray
    owners: np.ndarray
    log_weights: np.ndarray


def build_layout(sizes, accepted):
    sizes = list(sizes)
    if not sizes or any(
        isinstance(n, bool) or not isinstance(n, (int, np.integer)) or n < 3 for n in sizes
    ):
        raise ValueError("Integer race sizes >=3 required")
    accepted = _validate_orders(accepted, len(sizes))
    indices = []
    starts = []
    owners = []
    weights = []
    offset = 0
    for ri, (size, orders) in enumerate(zip(sizes, accepted, strict=True)):
        starts.append(len(indices))
        nsets = len({tuple(sorted(o)) for o in orders})
        for order in orders:
            if any(i < 0 or i >= size for i in order):
                raise ValueError("Order index outside race")
            indices.append([offset + i for i in order])
            owners.append(ri)
            weights.append(-np.log(nsets))
        offset += size
    return ConditionalLayout(
        offset, np.array(indices), np.array(starts), np.array(owners), np.array(weights)
    )


def score_loss_gradient(scores, layout):
    scores = np.asarray(scores, dtype=float)
    if scores.shape != (layout.n_rows,) or not np.isfinite(scores).all():
        raise ValueError("Finite aligned one-dimensional scores required")
    c = scores[layout.indices]
    lse1 = logsumexp(c, axis=1)
    lse2 = np.logaddexp(c[:, 1], c[:, 2])
    logp = c[:, 0] - lse1 + c[:, 1] - lse2 + layout.log_weights
    # Stable group logsumexp; each group has at least one accepted order.
    maximum = np.maximum.reduceat(logp, layout.starts)
    lse = maximum + np.log(np.add.reduceat(np.exp(logp - maximum[layout.owners]), layout.starts))
    posterior = np.exp(logp - lse[layout.owners])
    g = np.exp(c - lse1[:, None])
    g[:, 0] -= 1
    g[:, 1] -= 1
    g[:, 1:] += np.exp(c[:, 1:] - lse2[:, None])
    g *= posterior[:, None] / len(layout.starts)
    grad = np.zeros_like(scores)
    np.add.at(grad, layout.indices.ravel(), g.ravel())
    return float(-np.mean(lse)), grad


class ConditionalOrderMLP:
    def __init__(self, hidden_dim=16, l2=0.001, max_iter=100):
        if hidden_dim < 1 or l2 < 0 or max_iter < 1:
            raise ValueError("Invalid model parameters")
        self.hidden_dim = hidden_dim
        self.l2 = l2
        self.max_iter = max_iter

    def unpack(self, theta, d):
        h = self.hidden_dim
        return (
            theta[: d * h].reshape(d, h),
            theta[d * h : d * h + h],
            theta[d * h + h : d * h + 2 * h],
            theta[-1],
        )

    def forward(self, x, theta):
        w, b, v, a = self.unpack(theta, x.shape[1])
        hidden = np.tanh(x @ w + b)
        return hidden @ v + a, hidden

    def loss_gradient(self, theta, x, layout, regularize=True):
        score, h = self.forward(x, theta)
        loss, g = score_loss_gradient(score, layout)
        _, _, v, _ = self.unpack(theta, x.shape[1])
        z = g[:, None] * v * (1 - h * h)
        gradient = np.r_[(x.T @ z).ravel(), z.sum(axis=0), h.T @ g, g.sum()]
        if regularize:
            loss += 0.5 * self.l2 * (theta @ theta)
            gradient += self.l2 * theta
        return float(loss), gradient

    def fit(self, x, sizes, orders, *, tune, seed):
        x = np.asarray(x, dtype=float)
        tx = np.asarray(tune[0], dtype=float)
        if x.ndim != 2 or tx.ndim != 2 or x.shape[1] != tx.shape[1]:
            raise ValueError("Aligned matrices required")
        if not np.isfinite(x).all() or not np.isfinite(tx).all():
            raise ValueError("Finite inputs required")
        layout = build_layout(sizes, orders)
        tl = build_layout(tune[1], tune[2])
        if layout.n_rows != len(x) or tl.n_rows != len(tx):
            raise ValueError("Group size mismatch")
        d = x.shape[1]
        theta = np.random.default_rng(seed).normal(
            0, 0.05, d * self.hidden_dim + 2 * self.hidden_dim + 1
        )
        theta[-1] = 0
        best = theta.copy()
        best_loss = score_loss_gradient(self.forward(tx, theta)[0], tl)[0]
        iteration = 0
        selected = 0

        def callback(candidate):
            nonlocal best, best_loss, iteration, selected
            iteration += 1
            loss = score_loss_gradient(self.forward(tx, candidate)[0], tl)[0]
            if loss < best_loss:
                best = candidate.copy()
                best_loss = loss
                selected = iteration

        opt = minimize(
            lambda t: self.loss_gradient(t, x, layout),
            theta,
            jac=True,
            method="L-BFGS-B",
            callback=callback,
            options={"maxiter": self.max_iter, "ftol": 1e-12, "gtol": 1e-7, "maxls": 30},
        )
        self.theta_ = best
        self.n_features_in_ = d
        self.selected_iteration_ = selected
        self.tune_loss_ = float(best_loss)
        self.n_iter_ = int(opt.nit)
        self.converged_ = bool(opt.success)
        self.message_ = str(opt.message)
        return self

    def predict(self, x):
        x = np.asarray(x, dtype=float)
        if x.ndim != 2 or x.shape[1] != self.n_features_in_ or not np.isfinite(x).all():
            raise ValueError("Invalid prediction matrix")
        return self.forward(x, self.theta_)[0]
