"""Experience-aware coherent set calibration, optimized on race-balanced place loss."""

import numpy as np
from scipy.optimize import minimize

from horse_racing.analysis.jeju_joint_top3 import _group_logsumexp
from horse_racing.analysis.jeju_set_interaction import distribution, evaluate_set_race

OFFSET_NAMES = ["distance_0", "distance_1_2", "distance_3_5", "distance_unknown", "section_missing"]


def experience_design(distance_starts, early, closing):
    d = np.asarray(distance_starts, dtype=float)
    e = np.asarray(early, dtype=float)
    c = np.asarray(closing, dtype=float)
    if d.ndim != 1 or e.shape != d.shape or c.shape != d.shape:
        raise ValueError("Aligned one dimensional arrays required")
    known = np.isfinite(d)
    if np.any(d[known] < 0) or np.any(d[known] != np.floor(d[known])):
        raise ValueError("Historical start counts must be nonnegative integers")
    missing = ~np.isfinite(e) | ~np.isfinite(c)
    x = np.column_stack(
        [
            known & (d == 0),
            known & (d >= 1) & (d <= 2),
            known & (d >= 3) & (d <= 5),
            ~known,
            missing,
        ]
    ).astype(float)
    groups = np.where(
        ~known,
        "unknown",
        np.where(d == 0, "0", np.where(d <= 2, "1-2", np.where(d <= 5, "3-5", "6+"))),
    )
    return x, groups.tolist(), missing.tolist()


def objective_gradient(theta, base, set_design, layout, labels, l2=0.01):
    scale = np.exp(theta[0])
    logits = scale * base + set_design @ theta[1:]
    norm = _group_logsumexp(logits, layout.set_starts, layout.set_ends)
    p = np.exp(logits - norm[layout.set_owners])
    marginal = np.bincount(
        layout.set_indices.ravel(), weights=np.repeat(p, 3), minlength=len(labels)
    )
    # N=3 contributes constant zero loss; clipping keeps the derivative numerically finite.
    q = np.clip(marginal, 1e-12, 1 - 1e-12)
    weights = np.repeat(1 / layout.group_sizes, layout.group_sizes) / layout.n_races
    loss = -np.sum(weights * (labels * np.log(q) + (1 - labels) * np.log1p(-q)))
    g = weights * (q - labels) / (q * (1 - q))
    byset = g[layout.set_indices].sum(axis=1)
    expectation = np.add.reduceat(p * byset, layout.set_starts)
    gl = p * (byset - expectation[layout.set_owners])
    grad = np.r_[gl @ (scale * base), set_design.T @ gl]
    return float(loss + 0.5 * l2 * (theta @ theta)), grad + l2 * theta


class ExperienceSetCalibrator:
    def __init__(self, grouped=True, l2=0.01, max_iter=150):
        if l2 < 0 or max_iter < 1:
            raise ValueError("Invalid calibration settings")
        self.grouped, self.l2, self.max_iter = grouped, l2, max_iter

    def fit(self, base, design, layout, labels):
        base, design, labels = np.asarray(base), np.asarray(design), np.asarray(labels)
        if base.shape != (len(layout.set_indices),) or design.shape != (len(base), 5):
            raise ValueError("Set design mismatch")
        if labels.shape != (int(layout.group_sizes.sum()),):
            raise ValueError("Label layout mismatch")
        if not np.isfinite(base).all() or not np.isfinite(design).all():
            raise ValueError("Finite predictors required")
        if not np.isin(labels, [0, 1]).all():
            raise ValueError("Binary labels required")
        if not np.all(np.add.reduceat(labels, layout.race_starts) == 3):
            raise ValueError("Exclude boundary-tie races from binary calibration")
        z = design if self.grouped else design[:, :0]
        opt = minimize(
            lambda t: objective_gradient(t, base, z, layout, labels, self.l2),
            np.zeros(1 + z.shape[1]),
            jac=True,
            method="L-BFGS-B",
            bounds=[(-2, 2)] * (1 + z.shape[1]),
            options={"maxiter": self.max_iter, "ftol": 1e-12, "gtol": 1e-8, "maxls": 30},
        )
        self.theta_ = opt.x
        self.success_, self.n_iter_, self.message_ = (
            bool(opt.success),
            int(opt.nit),
            str(opt.message),
        )
        self.objective_ = float(opt.fun)
        self.at_boundary_ = bool(np.any(abs(opt.x) > 1.999))
        return self

    def predict_logits(self, base, design):
        z = design if self.grouped else design[:, :0]
        return np.exp(self.theta_[0]) * base + z @ self.theta_[1:]


def evaluate_policy(ids, logits, order, accepted, official, beta_order, fixed=None):
    result = evaluate_set_race(ids, logits, order, accepted, official, beta_order=beta_order)
    if fixed is None:
        return result
    sets, orders, ls, lo, marginals = distribution(logits, order, beta_order=beta_order)
    lookup = {h: i for i, h in enumerate(ids)}
    pick = lookup[fixed["pick_horse_id"]]
    wanted_set = set(fixed["predicted_set"])
    si = next(i for i, s in enumerate(sets) if {ids[j] for j in s} == wanted_set)
    wanted_order = fixed["predicted_order"]
    oi = next(i for i, o in enumerate(orders) if [ids[j] for j in o] == wanted_order)
    official_set = set(official)
    set_hit = any(set(o) == wanted_set for o in accepted)
    order_hit = tuple(wanted_order) in {tuple(o) for o in accepted}
    result.update(
        pick_horse_id=ids[pick],
        pick_hit=ids[pick] in official_set,
        pick_probability=float(marginals[pick]),
        tie_expected_pick_hit=float(ids[pick] in official_set),
        predicted_set=fixed["predicted_set"],
        predicted_order=wanted_order,
        set_hit=set_hit,
        order_hit=order_hit,
        order_given_set=order_hit if set_hit else None,
        set_confidence=float(np.exp(ls[si])),
        order_confidence=float(np.exp(lo[oi])),
        compatible_max_overlap=max(len(wanted_set & set(o)) for o in accepted),
    )
    return result
