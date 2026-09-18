"""Normalized three-horse set model with optional symmetric pair/triple terms."""

from __future__ import annotations

import numpy as np
from scipy.optimize import minimize
from scipy.special import logsumexp
from scipy.stats import rankdata

from horse_racing.analysis.jeju_conditional_order import ConditionalOrderMLP
from horse_racing.analysis.jeju_hybrid_evaluation import layouts
from horse_racing.analysis.jeju_joint_evaluation import (
    _binary_metrics,
    _id_key,
    _is_tie,
    _validate_accepted_orders,
    _validate_beta,
    _validate_ids,
    _validate_official_top3,
    _validate_scores,
)
from horse_racing.analysis.jeju_joint_top3 import _group_logsumexp

INTERACTION_INPUTS = [
    "global_elo_pre",
    "distance_elo_pre",
    "historical_early_front_rate",
    "closing_speed_quality_mean_3",
    "declared_horse_number_fraction",
    "declared_burden_kg",
    "current_vs_previous_rival_elo",
    "days_since_previous_start",
]
CROSSES = [(2, 3), (2, 4), (0, 5)]
INTERACTION_NAMES = (
    [f"pair_product__{c}" for c in INTERACTION_INPUTS]
    + [f"triple_product__{c}" for c in INTERACTION_INPUTS]
    + [f"cross_pair__{INTERACTION_INPUTS[a]}__{INTERACTION_INPUTS[b]}" for a, b in CROSSES]
)


def interaction_features(raw, sizes):
    """Only contemporaneous field covariates; midranks, missing=0, no fitted stats."""
    raw = np.asarray(raw, dtype=float)
    if raw.ndim != 2 or raw.shape[1] != len(INTERACTION_INPUTS):
        raise ValueError("Expected the fixed interaction inputs")
    if sum(sizes) != len(raw) or any(s < 3 for s in sizes):
        raise ValueError("Invalid group sizes")
    result = []
    start = 0
    for size in sizes:
        field = raw[start : start + size]
        ranks = np.zeros_like(field)
        for j, column in enumerate(field.T):
            ok = np.isfinite(column)
            if ok.sum() > 1:
                ranks[ok, j] = 2 * (rankdata(column[ok], method="average") - 1) / (ok.sum() - 1) - 1
        sets, _ = layouts(size)
        z = ranks[sets]
        pairs = (z[:, 0] * z[:, 1] + z[:, 0] * z[:, 2] + z[:, 1] * z[:, 2]) / 3
        triples = z.prod(axis=1)
        cross = np.column_stack(
            [
                (
                    z[:, :, a].sum(axis=1) * z[:, :, b].sum(axis=1)
                    - (z[:, :, a] * z[:, :, b]).sum(axis=1)
                )
                / 6
                for a, b in CROSSES
            ]
        )
        result.append(np.column_stack([pairs, triples, cross]))
        start += size
    return np.concatenate(result)


def set_loss_gradient(logits, layout):
    logits = np.asarray(logits, dtype=float)
    if logits.shape != (len(layout.set_indices),) or not np.isfinite(logits).all():
        raise ValueError("Invalid set logits")
    total = _group_logsumexp(logits, layout.set_starts, layout.set_ends)
    good = _group_logsumexp(
        logits[layout.accepted_set_indices], layout.accepted_set_starts, layout.accepted_set_ends
    )
    gradient = np.exp(logits - total[layout.set_owners])
    gradient[layout.accepted_set_indices] -= np.exp(
        logits[layout.accepted_set_indices] - good[layout.accepted_set_owners]
    )
    gradient /= layout.n_races
    return float(np.mean(total - good)), gradient


class SetInteractionMLP(ConditionalOrderMLP):
    def logits(self, x, z, layout, theta):
        cut = x.shape[1] * self.hidden_dim + 2 * self.hidden_dim + 1
        score, hidden = self.forward(x, theta[:cut])
        return score[layout.set_indices].sum(axis=1) + z @ theta[cut:], hidden

    def loss_gradient(self, theta, x, z, layout, regularize=True):
        cut = x.shape[1] * self.hidden_dim + 2 * self.hidden_dim + 1
        logits, hidden = self.logits(x, z, layout, theta)
        loss, gset = set_loss_gradient(logits, layout)
        g = np.bincount(layout.set_indices.ravel(), weights=np.repeat(gset, 3), minlength=len(x))
        _, _, v, _ = self.unpack(theta[:cut], x.shape[1])
        back = g[:, None] * v * (1 - hidden * hidden)
        gradient = np.r_[(x.T @ back).ravel(), back.sum(axis=0), hidden.T @ g, g.sum(), z.T @ gset]
        if regularize:
            loss += 0.5 * self.l2 * (theta @ theta)
            gradient += self.l2 * theta
        return float(loss), gradient

    def fit(self, x, z, layout, *, tune, seed):
        tx, tz, tl = tune
        for a, b, layout_ in [(x, z, layout), (tx, tz, tl)]:
            if a.ndim != 2 or b.ndim != 2 or not np.isfinite(a).all() or not np.isfinite(b).all():
                raise ValueError("Finite matrices required")
            if len(a) != layout_.group_sizes.sum() or len(b) != len(layout_.set_indices):
                raise ValueError("Layout mismatch")
        if x.shape[1] != tx.shape[1] or z.shape[1] != tz.shape[1]:
            raise ValueError("Feature mismatch")
        cut = x.shape[1] * self.hidden_dim + 2 * self.hidden_dim + 1
        theta = np.r_[np.random.default_rng(seed).normal(0, 0.05, cut), np.zeros(z.shape[1])]
        theta[cut - 1] = 0
        best = theta.copy()
        best_loss = set_loss_gradient(self.logits(tx, tz, tl, theta)[0], tl)[0]
        iteration, selected = 0, 0

        def callback(candidate):
            nonlocal best, best_loss, iteration, selected
            iteration += 1
            loss = set_loss_gradient(self.logits(tx, tz, tl, candidate)[0], tl)[0]
            if loss < best_loss:
                best, best_loss, selected = candidate.copy(), loss, iteration

        opt = minimize(
            lambda t: self.loss_gradient(t, x, z, layout),
            theta,
            jac=True,
            method="L-BFGS-B",
            callback=callback,
            options={"maxiter": self.max_iter, "ftol": 1e-12, "gtol": 1e-7, "maxls": 30},
        )
        self.theta_ = best
        self.n_features_in_, self.n_interactions_ = x.shape[1], z.shape[1]
        self.selected_iteration_, self.tune_loss_ = selected, float(best_loss)
        self.n_iter_, self.converged_, self.message_ = (
            int(opt.nit),
            bool(opt.success),
            str(opt.message),
        )
        return self

    def predict_sets(self, x, z, layout):
        if x.shape[1] != self.n_features_in_ or z.shape[1] != self.n_interactions_:
            raise ValueError("Feature mismatch")
        return self.logits(x, z, layout, self.theta_)[0]


def distribution(logits, order_scores, beta_set=1.0, beta_order=1.0):
    b = np.asarray(order_scores, dtype=float) * beta_order
    a = np.asarray(logits, dtype=float) * beta_set
    sets, orders = layouts(len(b))
    if a.shape != (len(sets),) or not np.isfinite(a).all() or not np.isfinite(b).all():
        raise ValueError("Invalid set/order scores")
    if beta_set <= 0 or beta_order <= 0:
        raise ValueError("Positive temperatures required")
    ls = a - logsumexp(a)
    c = b[orders]
    conditional = c[:, 0] - logsumexp(c, axis=1) + c[:, 1] - np.logaddexp(c[:, 1], c[:, 2])
    joint = np.repeat(ls, 6) + conditional
    marginal = np.bincount(sets.ravel(), weights=np.repeat(np.exp(ls), 3), minlength=len(b))
    return sets, orders, ls, joint, marginal


def evaluate_set_race(
    horse_ids,
    set_logits,
    order_scores,
    accepted_orders,
    official_top3_ids,
    *,
    beta_set=1.0,
    beta_order=1.0,
):
    ids = _validate_ids(horse_ids)
    a = np.asarray(set_logits, dtype=float)
    b = _validate_scores(order_scores, len(ids), "order_scores")
    bs = _validate_beta(beta_set, "beta_set")
    bo = _validate_beta(beta_order, "beta_order")
    _, accepted = _validate_accepted_orders(accepted_orders, ids)
    official = _validate_official_top3(official_top3_ids, ids)
    sets, orders, ls, lo, marginals = distribution(a, b, bs, bo)
    keys = [_id_key(h) for h in ids]
    setkeys = [tuple(sorted(keys[i] for i in s)) for s in sets]
    orderkeys = [tuple(keys[i] for i in o) for o in orders]
    accepted_sets = {tuple(sorted(o)) for o in accepted}

    def best(values, keylist):
        maximum = max(values)
        return min(
            (i for i, v in enumerate(values) if _is_tie(float(v), float(maximum))),
            key=lambda i: keylist[i],
        )

    si = best(ls, setkeys)
    oi = si * 6 + best(lo[si * 6 : si * 6 + 6], orderkeys[si * 6 : si * 6 + 6])
    gi = best(lo, orderkeys)
    pi = best(marginals, keys)  # Select the largest coherent inclusion probability.
    labels = [int(k in official) for k in keys]
    brier, binary_loss = _binary_metrics(marginals, labels)
    max_p = max(marginals)
    tied_p = [i for i, v in enumerate(marginals) if _is_tie(float(v), float(max_p))]
    set_hit = setkeys[si] in accepted_sets
    order_hit = orderkeys[oi] in accepted
    return dict(
        pick_horse_id=ids[pi],
        pick_hit=bool(labels[pi]),
        pick_probability=float(marginals[pi]),
        tie_expected_pick_hit=float(np.mean([labels[i] for i in tied_p])),
        pl_marginals=marginals.tolist(),
        official_labels=labels,
        place_brier=brier,
        place_logloss=binary_loss,
        predicted_set=sorted([ids[i] for i in sets[si]], key=_id_key),
        predicted_order=[ids[i] for i in orders[oi]],
        set_hit=bool(set_hit),
        order_hit=bool(order_hit),
        order_given_set=bool(order_hit) if set_hit else None,
        set_nll=float(
            -logsumexp([v for v, k in zip(ls, setkeys, strict=True) if k in accepted_sets])
        ),
        order_nll=float(
            -logsumexp([v for v, k in zip(lo, orderkeys, strict=True) if k in accepted])
        ),
        set_confidence=float(np.exp(ls[si])),
        order_confidence=float(np.exp(lo[oi])),
        global_predicted_order=[ids[i] for i in orders[gi]],
        global_order_hit=bool(orderkeys[gi] in accepted),
        global_order_confidence=float(np.exp(lo[gi])),
        set_probability_sum=float(np.exp(ls).sum()),
        order_probability_sum=float(np.exp(lo).sum()),
        compatible_max_overlap=max(len(set(setkeys[si]) & set(s)) for s in accepted_sets),
    )
