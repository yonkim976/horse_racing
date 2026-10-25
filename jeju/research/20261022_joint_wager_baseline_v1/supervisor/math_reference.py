"""Independent supervisory probability and scoring calculations.

No experiment imports, fitting, database access, or source writes.
"""
import itertools
import math
from collections import defaultdict

import numpy as np

CATEGORICAL = {'WIN', 'QNL', 'EXA', 'TLA', 'TRI'}


def reference_distribution(scores, temperature):
    """Enumerate via nested conditional draws and explicit remaining sets."""
    u = np.asarray(scores, dtype=float) / float(temperature)
    n = len(u)
    indices = np.arange(n)
    first_weights = np.exp(u - u.max())
    first = first_weights / math.fsum(first_weights)
    joint = {}
    for i in indices:
        remaining = indices[indices != i]
        second_weights = np.exp(u[remaining] - max(u[remaining]))
        second = second_weights / math.fsum(second_weights)
        for j, second_p in zip(remaining, second):
            remaining2 = remaining[remaining != j]
            third_weights = np.exp(u[remaining2] - max(u[remaining2]))
            third = third_weights / math.fsum(third_weights)
            for k, third_p in zip(remaining2, third):
                joint[(int(i), int(j), int(k))] = float(first[i] * second_p * third_p)
    assert len(joint) == n * (n - 1) * (n - 2)
    assert abs(math.fsum(joint.values()) - 1) < 1e-12
    return joint


def aggregate(joint, n, plc_places):
    pools = {p: defaultdict(float) for p in ['WIN', 'PLC', 'QNL', 'QPL', 'EXA', 'TLA', 'TRI']}
    ranks = np.zeros((n, 3), dtype=float)
    for order, prob in joint.items():
        i, j, k = order
        pools['WIN'][(i,)] += prob
        pools['EXA'][(i, j)] += prob
        pools['QNL'][tuple(sorted((i, j)))] += prob
        pools['TLA'][tuple(sorted(order))] += prob
        pools['TRI'][order] = prob
        for pair in itertools.combinations(sorted(order), 2):
            pools['QPL'][pair] += prob
        for rank, horse in enumerate(order):
            ranks[horse, rank] += prob
        if plc_places is not None:
            for horse in order[:plc_places]:
                pools['PLC'][(horse,)] += prob
    for pool in CATEGORICAL:
        assert abs(math.fsum(pools[pool].values()) - 1) < 1e-12
    assert abs(math.fsum(pools['QPL'].values()) - 3) < 1e-12
    if plc_places is not None:
        assert abs(math.fsum(pools['PLC'].values()) - plc_places) < 1e-12
    assert np.allclose(ranks.sum(axis=0), 1, atol=1e-12, rtol=0)
    top2, top3 = ranks[:, :2].sum(axis=1), ranks.sum(axis=1)
    assert np.all(ranks[:, 0] <= top2) and np.all(top2 <= top3)
    for horse in range(n):
        qnl_incident = math.fsum(p for key, p in pools['QNL'].items() if horse in key)
        qpl_incident = math.fsum(p for key, p in pools['QPL'].items() if horse in key)
        assert abs(qnl_incident - top2[horse]) < 1e-12
        assert abs(qpl_incident - 2 * top3[horse]) < 1e-12
    return pools, ranks


def winners(pool, actual, plc_places):
    if pool == 'WIN':
        return {(actual[0],)}
    if pool == 'PLC':
        return {(i,) for i in actual[:plc_places]}
    if pool == 'EXA':
        return {tuple(actual[:2])}
    if pool == 'QNL':
        return {tuple(sorted(actual[:2]))}
    if pool == 'TRI':
        return {tuple(actual)}
    if pool == 'TLA':
        return {tuple(sorted(actual))}
    if pool == 'QPL':
        return set(itertools.combinations(sorted(actual), 2))
    raise ValueError(pool)


def score_events(pool, probs, actual, plc_places, epsilon=1e-15):
    truth = winners(pool, actual, plc_places)
    keys = sorted(probs)
    p = np.array([probs[key] for key in keys])
    y = np.array([key in truth for key in keys], dtype=float)
    cp = np.clip(p, epsilon, 1 - epsilon)
    if pool in CATEGORICAL:
        ll = -math.log(max(probs[next(iter(truth))], epsilon))
        bs = math.fsum((p - y) ** 2)
    else:
        ll = float(np.mean(-y * np.log(cp) - (1 - y) * np.log1p(-cp)))
        bs = float(np.mean((p - y) ** 2))
    chosen = min(keys, key=lambda key: (-probs[key], key))
    return dict(log_loss=ll, brier=bs, selected_key=chosen,
                selected_probability=probs[chosen], selected_hit=int(chosen in truth)), keys, p, y


def inverse_temperature_derivatives(calibration_races, temperature):
    """Convex NLL in inverse T: gradient=sum(E[s]−s_winner), Hessian=sum Var[s]."""
    alpha = 1.0 / temperature
    gradients, curvatures, losses = [], [], []
    for scores, actual in calibration_races:
        scores = np.asarray(scores, dtype=float)
        remaining = list(range(len(scores)))
        gradient = curvature = loss = 0.0
        for chosen in actual:
            s = scores[remaining]
            scaled = alpha * s
            m = max(scaled)
            weights = np.exp(scaled - m)
            denominator = math.fsum(weights)
            prob = weights / denominator
            mean = float(prob @ s)
            gradient += mean - scores[chosen]
            curvature += float(prob @ ((s - mean) ** 2))
            loss += m + math.log(denominator) - alpha * scores[chosen]
            remaining.remove(chosen)
        gradients.append(gradient)
        curvatures.append(curvature)
        losses.append(loss)
    return dict(nll=float(np.mean(losses)), gradient_inverse_t=float(np.mean(gradients)),
                hessian_inverse_t=float(np.mean(curvatures)))


def synthetic():
    for n in (5, 7, 8, 10):
        joint = reference_distribution(np.zeros(n), 1.0)
        k = 2 if n < 8 else 3
        pools, ranks = aggregate(joint, n, k)
        expected = {'WIN': 1 / n, 'PLC': k / n, 'QNL': 2 / (n * (n - 1)),
                    'QPL': 6 / (n * (n - 1)), 'EXA': 1 / (n * (n - 1)),
                    'TLA': 6 / (n * (n - 1) * (n - 2)),
                    'TRI': 1 / (n * (n - 1) * (n - 2))}
        for pool, p in pools.items():
            assert np.allclose(list(p.values()), expected[pool], atol=1e-12, rtol=0)
    scores = np.array([-2.0, -.5, 0., .2, 1., 3., 4., 6.])
    base = reference_distribution(scores, 1.3)
    shifted = reference_distribution(scores + 1000, 1.3)
    assert max(abs(base[k] - shifted[k]) for k in base) < 1e-12
    return {'uniform_5_7_8_10': True, 'shift_invariance': True,
            'incidence_and_probability_sums': True}


if __name__ == '__main__':
    print(synthetic())
