"""Coherent probability mixtures and a conditional Top2-to-third factor."""
from __future__ import annotations
from functools import lru_cache
from itertools import permutations

import numpy as np
from scipy.optimize import minimize_scalar
from scipy.special import logsumexp

from common import prob


def vector(values, name):
    a = np.asarray(values, dtype=float)
    if a.ndim != 1 or not np.isfinite(a).all():
        raise ValueError(f"{name} must be a finite one-dimensional vector")
    return a


def temperature(value):
    t = float(value)
    if not np.isfinite(t) or t <= 0:
        raise ValueError("temperature must be positive and finite")
    return t


def mixed(a, b, weight):
    a, b = vector(a, "a"), vector(b, "b")
    w = float(weight)
    if a.shape != b.shape or np.any(a < 0) or np.any(b < 0):
        raise ValueError("probabilities must have equal shape and be nonnegative")
    if not np.isfinite(w) or not 0 <= w <= 1:
        raise ValueError("weight must be in [0,1]")
    if not np.isclose(a.sum(), 1, atol=1e-10, rtol=0) or not np.isclose(b.sum(), 1, atol=1e-10, rtol=0):
        raise ValueError("distributions must sum to one")
    return w * a + (1 - w) * b


@lru_cache(maxsize=32)
def order_support(n):
    triples, _ = prob.support(n)
    positions = np.array(list(permutations(range(3))), dtype=int)
    orders = triples[:, positions].reshape(-1, 3)
    orders.setflags(write=False)
    return orders


def top2_ordered(scores2, scores_first, q, temp_third, temp_first):
    s2, sf, q = vector(scores2, "scores2"), vector(scores_first, "scores_first"), vector(q, "q")
    if len(s2) < 3 or len(sf) != len(s2):
        raise ValueError("scores must refer to the same field with at least three runners")
    triples, _ = prob.support(len(s2))
    if len(q) != len(triples) or np.any(q < 0) or not np.isclose(q.sum(), 1, atol=1e-10, rtol=0):
        raise ValueError("q must be a normalized trio distribution")
    t3, t12 = temperature(temp_third), temperature(temp_first)
    orders = order_support(len(s2))
    z3 = -s2 / t3
    denominator = np.repeat(logsumexp(z3[triples], axis=1), 6)
    log_third = z3[orders[:, 2]] - denominator
    pair_delta = (sf[orders[:, 0]] - sf[orders[:, 1]]) / t12
    log_first = -np.logaddexp(0, -pair_delta)
    mass = np.repeat(q, 6) * np.exp(log_third + log_first)
    assert np.isclose(mass.sum(), 1, rtol=0, atol=1e-10)
    assert np.allclose(mass.reshape(-1, 6).sum(axis=1), q, rtol=0, atol=1e-12)
    return orders, mass


def actual_indices(outcome, n):
    y = vector(outcome, "outcome")
    if len(y) != n:
        raise ValueError("outcome and scores must have equal length")
    indices=[]
    for rank in [1, 2, 3]:
        ix=np.flatnonzero(y == rank)
        if len(ix) != 1:
            raise ValueError("outcome must have unique ranks 1, 2, and 3")
        indices.append(int(ix[0]))
    return indices


def bounded_minimum(objective, bounds):
    low, high = map(float, bounds)
    if not np.isfinite([low, high]).all() or low >= high:
        raise ValueError("invalid bounds")
    fit = minimize_scalar(objective, bounds=(low, high), method="bounded", options={"xatol": 1e-7})
    if not fit.success:
        raise RuntimeError(str(fit.message))
    candidates = [(float(objective(t)), float(t)) for t in [low, float(fit.x), high]]
    loss, value = min(candidates)
    return value, {"success": True, "loss": loss, "at_boundary": bool(value in [low, high])}


def selected_scores(records):
    rows=[]
    for scores, outcome in records:
        s=vector(scores,"scores")
        rows.append(s[actual_indices(outcome,len(s))])
    if not rows:
        raise ValueError("at least one calibration race is required")
    return np.array(rows)


def fit_third_temperature(records, bounds=(.35, 4.)):
    s=selected_scores(records)
    if bounds[0] <= 0:
        raise ValueError("temperature bounds must be positive")
    return bounded_minimum(lambda t: float(np.mean(logsumexp(-s/t,axis=1)+s[:,2]/t)),bounds)[0]


def fit_first_temperature(records, bounds=(.35, 4.)):
    s=selected_scores(records)
    if bounds[0] <= 0:
        raise ValueError("temperature bounds must be positive")
    return bounded_minimum(lambda t: float(np.mean(np.logaddexp(0,(s[:,1]-s[:,0])/t))),bounds)[0]


def fit_mixture_weight(prob_el, prob_f):
    a,b=vector(prob_el,"prob_el"),vector(prob_f,"prob_f")
    if a.shape != b.shape or not len(a) or np.any(a<=0) or np.any(b<=0) or np.any(a>1) or np.any(b>1):
        raise ValueError("positive actual-outcome probabilities in (0,1] required")
    return bounded_minimum(lambda w: float(-np.log(w*a+(1-w)*b).mean()),(0,1))
