"""Preserve a ranker's entire PL set distribution, replace within-set order."""

from __future__ import annotations

from functools import lru_cache
from itertools import combinations, permutations

import numpy as np
from scipy.special import logsumexp

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


@lru_cache(maxsize=32)
def layouts(n):
    sets = np.array(list(combinations(range(n), 3)), dtype=int)
    perms = np.array(list(permutations(range(3))), dtype=int)
    orders = sets[:, perms].reshape(-1, 3)
    return sets, orders


def distribution(set_scores, order_scores, beta_set=1.0, beta_order=1.0):
    a = np.asarray(set_scores, dtype=float) * beta_set
    b = np.asarray(order_scores, dtype=float) * beta_order
    if a.ndim != 1 or a.shape != b.shape or len(a) < 3:
        raise ValueError("Aligned one-dimensional scores for at least three starters required")
    if not np.isfinite(a).all() or not np.isfinite(b).all():
        raise ValueError("Finite scores required")
    a = a - a.max()
    b = b - b.max()
    n = len(a)
    sets, orders = layouts(n)
    den0 = logsumexp(a)
    den1 = np.array([logsumexp(np.delete(a, i)) for i in range(n)])
    den2 = np.zeros((n, n))
    for i in range(n):
        for j in range(i + 1, n):
            den2[i, j] = den2[j, i] = logsumexp(np.delete(a, [i, j]))
    base_order = (
        a[orders].sum(axis=1) - den0 - den1[orders[:, 0]] - den2[orders[:, 0], orders[:, 1]]
    )
    log_sets = logsumexp(base_order.reshape(-1, 6), axis=1)
    c = b[orders]
    conditional = c[:, 0] - logsumexp(c, axis=1) + c[:, 1] - np.logaddexp(c[:, 1], c[:, 2])
    joint = np.repeat(log_sets, 6) + conditional
    marginals = np.bincount(sets.ravel(), weights=np.repeat(np.exp(log_sets), 3), minlength=n)
    return sets, orders, log_sets, joint, marginals


def accepted_layout(horse_ids, set_scores, order_scores, accepted_orders, beta_set):
    """Precompute CAL constants; no outcome-dependent model scores are produced."""
    ids = list(horse_ids)
    sets, orders, log_sets, _, _ = distribution(set_scores, order_scores, beta_set, 1.0)
    index = {h: i for i, h in enumerate(ids)}
    lookup = {tuple(s): k for k, s in enumerate(sets)}
    local = np.array([[index[h] for h in o] for o in accepted_orders])
    return np.array([log_sets[lookup[tuple(sorted(o))]] for o in local]), np.asarray(order_scores)[
        local
    ]


def conditional_calibration_loss(log_beta, layouts_):
    beta = np.exp(log_beta)
    losses = []
    for log_sets, raw in layouts_:
        b = raw * beta
        cond = b[:, 0] - logsumexp(b, axis=1) + b[:, 1] - np.logaddexp(b[:, 1], b[:, 2])
        losses.append(-logsumexp(log_sets + cond))
    return float(np.mean(losses))


def evaluate_hybrid_race(
    horse_ids,
    set_scores,
    order_scores,
    accepted_orders,
    official_top3_ids,
    *,
    beta_set=1.0,
    beta_order=1.0,
):
    ids = _validate_ids(horse_ids)
    a = _validate_scores(set_scores, len(ids), "set_scores")
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
    pi = best(a, keys)  # Preserve the original ranker pick, including all-included N=3.
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
