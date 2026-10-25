"""Synthetic-only controls for the predeclared successful-set event likelihood."""
from pathlib import Path
from itertools import combinations
import json
import numpy as np
from scipy.special import logsumexp

HERE = Path(__file__).resolve().parent


def objective(beta, datasets, lam=1.0):
    value = 0.0
    gradient = np.zeros_like(beta)
    for prior, phi, good in datasets:
        energy = prior + phi @ beta
        all_z = logsumexp(energy)
        good_z = logsumexp(energy[good])
        all_p = np.exp(energy - all_z)
        good_p = np.exp(energy[good] - good_z)
        value += all_z - good_z
        gradient += all_p @ phi - good_p @ phi[good]
    return value / len(datasets) + lam * beta @ beta / 2, gradient / len(datasets) + lam * beta


def main():
    rng = np.random.default_rng(20261025)
    data = []
    for n in [6, 7, 10, 12]:
        sets = np.array(list(combinations(range(n), 5)))
        prior = rng.normal(size=n)[sets].sum(axis=1)
        phi = rng.normal(size=(len(sets), 5))
        good = np.array([set([0, 1, 2]) <= set(s) for s in sets])
        assert good.sum() == (n - 3) * (n - 4) // 2
        data.append((prior, phi, good))
    max_error = 0.0
    for beta in [np.zeros(5), rng.normal(size=5) * .1, rng.normal(size=5)]:
        value, grad = objective(beta, data)
        numerical = np.zeros(5)
        for k in range(5):
            delta = np.zeros(5); delta[k] = 1e-6
            numerical[k] = (objective(beta + delta, data)[0] - objective(beta - delta, data)[0]) / 2e-6
        max_error = max(max_error, float(np.max(np.abs(numerical - grad))))
        shifted = [(p + 1000, x, y) for p, x, y in data]
        reversed_data = [(p[::-1], x[::-1], y[::-1]) for p, x, y in data]
        for transformed in [shifted, reversed_data]:
            v, g = objective(beta, transformed)
            assert abs(value - v) < 1e-11 and np.max(np.abs(g - grad)) < 1e-11
    # When all runners fit in five, every set is successful: no data gradient.
    beta = np.arange(5) * .1
    loss, grad = objective(beta, [(np.array([17.]), rng.normal(size=(1, 5)), np.array([True]))])
    assert np.isclose(loss, .5 * beta @ beta) and np.allclose(grad, beta)
    assert max_error < 1e-8
    result = dict(passed=True, actual_eval_labels_read=False, synthetic_only=True,
                  finite_difference_max_abs_gradient_error=max_error,
                  subset_count_formula_checked=True, set_row_order_invariance=True,
                  energy_shift_invariance=True, field_n_5_no_information_control=True,
                  objective='mean(log Z_all - log Z_successful) + 0.5 lambda ||beta||^2',
                  note='Gibbs selector training loss; not a calibrated probability of deterministic top5 success; nonconvex in general.')
    with (HERE / 'ROOT_OBJECTIVE_CONTROLS.json').open('x') as f:
        json.dump(result, f, indent=2); f.write('\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
