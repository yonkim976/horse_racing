"""Independent Bottom3 reference; no experiment import, fitting or file mutation."""
import itertools
import math

import numpy as np

EPS = 1e-15


def distribution(utilities, temperature):
    u = [float(x) for x in utilities]
    assert len(u) >= 3 and all(math.isfinite(x) for x in u)
    assert math.isfinite(temperature) and temperature > 0
    keys = list(itertools.combinations(range(len(u)), 3))
    sums = [math.fsum(u[i] for i in key) for key in keys]
    peak = max(sums)
    unscaled = [math.exp((a - peak) / temperature) for a in sums]
    denominator = math.fsum(unscaled)
    probabilities = {key: v / denominator for key, v in zip(keys, unscaled)}
    marginals = np.array([math.fsum(p for key, p in probabilities.items() if i in key)
                          for i in range(len(u))])
    assert abs(math.fsum(probabilities.values()) - 1) < 2e-13
    assert abs(math.fsum(marginals) - 3) < 5e-13
    assert all(0 <= p <= 1 for p in probabilities.values())
    assert np.all((marginals >= 0) & (marginals <= 1 + 2e-15))
    return probabilities, marginals


def select(utilities, horse_numbers):
    remaining = dict(zip(map(int, horse_numbers), map(float, utilities)))
    chosen = []
    for _ in range(3):
        maximum = max(remaining.values())
        number = min(k for k, value in remaining.items() if value >= maximum - 1e-12)
        chosen.append(number)
        del remaining[number]
    return tuple(chosen)


def metrics(utilities, temperature, ranks, horse_numbers):
    ranks = np.asarray(ranks, int)
    numbers = np.asarray(horse_numbers, int)
    n = len(ranks)
    assert sorted(ranks.tolist()) == list(range(1, n + 1))
    actual = tuple(np.flatnonzero(ranks >= n - 2))
    probabilities, marginals = distribution(utilities, temperature)
    y = np.isin(np.arange(n), actual).astype(float)
    q = np.clip(marginals, EPS, 1 - EPS)
    chosen = select(utilities, numbers)
    selected = np.isin(numbers, chosen)
    captured = int(np.sum(selected & (ranks >= n - 2)))
    excluded_top3 = int(np.sum(selected & (ranks <= 3)))
    result = {
        'set_nll': -math.log(max(probabilities[actual], EPS)),
        'set_brier': math.fsum((p - float(key == actual)) ** 2 for key, p in probabilities.items()),
        'runner_nll': float(np.mean(-y * np.log(q) - (1 - y) * np.log1p(-q))),
        'runner_brier': float(np.mean((marginals - y) ** 2)),
        'bottom3_capture_count': captured,
        'bottom3_precision_at3': captured / 3,
        'bottom3_exact_hit': int(captured == 3),
        'excluded_top3_count': excluded_top3,
        'excluded_any_top3': int(excluded_top3 > 0),
        'excluded_winner': int(np.any(selected & (ranks == 1))),
        'all_top3_retained': int(excluded_top3 == 0),
    }
    return result, probabilities, marginals, chosen, actual


def calibration_check(records, temperature):
    """Unclipped set NLL, gradient and Hessian in inverse temperature beta."""
    losses, gradients, hessians = [], [], []
    for utilities, ranks in records:
        u = np.asarray(utilities, float)
        n = len(u)
        actual = tuple(np.flatnonzero(np.asarray(ranks) >= n - 2))
        p, _ = distribution(u, temperature)
        a = {key: math.fsum(u[i] for i in key) for key in p}
        peak = max(a.values())
        log_z = peak / temperature + math.log(math.fsum(math.exp((x - peak) / temperature) for x in a.values()))
        mean_a = math.fsum(p[key] * value for key, value in a.items())
        losses.append(log_z - a[actual] / temperature)
        gradients.append(mean_a - a[actual])
        hessians.append(math.fsum(p[key] * (value - mean_a) ** 2 for key, value in a.items()))
    return {'objective_nll': math.fsum(losses) / len(records),
            'gradient_beta': math.fsum(gradients) / len(records),
            'hessian_beta': math.fsum(hessians) / len(records),
            'races': len(records)}


def synthetic():
    checks = 0
    for n in (6, 7, 10, 12):
        q, marginal = distribution(np.zeros(n), 1.0)
        assert all(abs(p - 1 / math.comb(n, 3)) < 1e-14 for p in q.values())
        assert np.max(np.abs(marginal - 3 / n)) < 1e-14
        u = np.linspace(-3, 2, n)
        a, ma = distribution(u, .83)
        b, mb = distribution(u + 200, .83)
        assert max(abs(a[k] - b[k]) for k in a) < 1e-13
        assert np.max(np.abs(ma - mb)) < 1e-13
        permutation = np.arange(n)[::-1]
        c, mc = distribution(u[permutation], .83)
        assert np.max(np.abs(mc - ma[permutation])) < 1e-14
        for key, p in c.items():
            assert abs(p - a[tuple(sorted(permutation[list(key)]))]) < 1e-14
        ranks = np.arange(1, n + 1)
        result, _, _, chosen, _ = metrics(u, .83, ranks, ranks)
        assert set(chosen) == set(range(n - 2, n + 1))
        assert result['bottom3_capture_count'] == 3
        assert result['excluded_any_top3'] == 0
        assert result['all_top3_retained'] == 1
        beta = 1 / .83
        delta = 1e-5
        base = calibration_check([(u, ranks)], 1 / beta)
        plus = calibration_check([(u, ranks)], 1 / (beta + delta))
        minus = calibration_check([(u, ranks)], 1 / (beta - delta))
        assert abs(base['gradient_beta'] - (plus['objective_nll'] - minus['objective_nll']) / (2 * delta)) < 1e-8
        assert abs(base['hessian_beta'] - (plus['gradient_beta'] - minus['gradient_beta']) / (2 * delta)) < 1e-8
        checks += 1
    assert select([1, 1 - 5e-13, 0, -1], [8, 2, 4, 5]) == (2, 8, 4)
    return {'passed': True, 'rosters': checks, 'uniform_mass_and_marginals': True,
            'shift_and_permutation_invariance': True, 'gradient_finite_difference': True,
            'selection_and_ties': True, 'new_real_data_performance_computed': False}


if __name__ == '__main__':
    import json
    print(json.dumps(synthetic(), indent=2))
