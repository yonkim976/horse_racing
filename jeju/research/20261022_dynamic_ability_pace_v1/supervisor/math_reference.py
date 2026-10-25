"""Independent numerical checks: explicit choice sets, no fitted estimator.

Only supervisory verification uses this module. The experiment cannot import it.
"""
import importlib.util
import math
import sys
from pathlib import Path

import numpy as np

sys.dont_write_bytecode = True
OLD = Path(__file__).resolve().parents[2] / '20261022_rank_stage_temperature_v1/supervisor/math_reference.py'
spec = importlib.util.spec_from_file_location('_sealed_supervisor_reference', OLD)
old = importlib.util.module_from_spec(spec)
spec.loader.exec_module(old)
aggregate = old.aggregate
score_events = old.score_events
winners = old.winners
stable_selection = old.stable_selection


def distribution(utility, temperature=1.0):
    return old.reference_distribution(utility, [temperature] * 3)


def mixture(utility0, utility1, q, temperature=1.0):
    assert np.isfinite(q) and 0 <= q <= 1
    a, b = distribution(utility0, temperature), distribution(utility1, temperature)
    result = {key: (1-q)*a[key] + q*b[key] for key in a}
    assert abs(math.fsum(result.values())-1) < 1e-12
    return result


def rank_loss_derivatives(utility, actual):
    """One race's Top3 loss and full Hessian, calculated independently."""
    u = np.asarray(utility, dtype=float)
    n = len(u)
    gradient, hessian = np.zeros(n), np.zeros((n, n))
    loss = 0.0
    available = list(range(n))
    for chosen in actual[:3]:
        values = u[available]
        maximum = max(values)
        weights = np.exp(values-maximum)
        denominator = math.fsum(weights)
        probabilities = weights/denominator
        loss += maximum + math.log(denominator) - u[chosen]
        gradient[available] += probabilities
        gradient[chosen] -= 1
        hessian[np.ix_(available, available)] += np.diag(probabilities)-np.outer(probabilities, probabilities)
        available.remove(int(chosen))
    return loss, gradient, hessian


def inverse_temperature_derivatives(utility, actual, temperature):
    u = np.asarray(utility, dtype=float)
    loss, gradient, hessian = rank_loss_derivatives(u/temperature, actual)
    return loss, float(gradient@u), float(u@hessian@u)


def synthetic():
    rng = np.random.default_rng(621022)
    max_grad_error = max_hess_error = 0.0
    checks = 0
    for n in (3, 5, 7, 8, 12):
        u = rng.normal(size=n)
        actual = rng.permutation(n)[:3]
        loss, grad, hess = rank_loss_derivatives(u, actual)
        q = distribution(u)
        assert abs(loss+math.log(q[tuple(actual)])) < 1e-12
        assert abs(grad.sum()) < 1e-12
        assert np.max(np.abs(hess.sum(axis=0))) < 1e-12
        for i in range(n):
            step = np.zeros(n); step[i] = 1e-5
            p, gp, _ = rank_loss_derivatives(u+step, actual)
            m, gm, _ = rank_loss_derivatives(u-step, actual)
            max_grad_error = max(max_grad_error, abs((p-m)/2e-5-grad[i]))
            max_hess_error = max(max_hess_error, float(np.max(np.abs((gp-gm)/2e-5-hess[:, i]))))
        for probability in (0., .3, 1.):
            mq = mixture(u, u[::-1], probability, 1.25)
            # The legal five-runner and seven-runner branches are synthetic only.
            plc = (2 if n < 8 else 3) if n >= 5 else None
            aggregate(mq, n, plc)
            if probability == 0:
                assert mq == distribution(u, 1.25)
            if probability == 1:
                assert mq == distribution(u[::-1], 1.25)
            checks += 1
    assert max_grad_error < 1e-8 and max_hess_error < 1e-8
    return {'passed': True, 'mixture_cases': checks,
            'max_finite_difference_gradient_error': max_grad_error,
            'max_finite_difference_full_hessian_error': max_hess_error,
            'full_choice_sets_and_mixture_marginal_identities': True}


if __name__ == '__main__':
    print(synthetic())
