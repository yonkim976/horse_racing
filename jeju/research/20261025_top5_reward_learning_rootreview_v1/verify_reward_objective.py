"""Synthetic-only audit of the actual executable reward objective.

Independent per-race brute-force expected rewards and derivatives are compared
with the reviewed implementation, including unequal probabilities per race.
"""
from pathlib import Path
from itertools import combinations
import importlib.util
import sys
import hashlib
import json
import numpy as np
import pandas as pd
from scipy.special import logsumexp

HERE = Path(__file__).resolve().parent
STUDY = HERE.parent / '20261025_top5_reward_learning_v1'
EXPECTED = '043c669ad6f8d7a9d66bb5846002758385c3e0811e7e6720727b2e5c1e9b85dc'


def independent(beta, data):
    value = 0.0
    grad = np.zeros_like(beta)
    probabilities = []
    for prior, x, good in data:
        energy = prior + x @ beta
        p = np.exp(energy - logsumexp(energy))
        reward = np.where(good, 1.0, -1.0)
        mean_reward = float(p @ reward)
        # Direct reward-weighted policy derivative, not the positive-mass helper.
        grad -= (p * (reward - mean_reward)) @ x
        value -= mean_reward
        probabilities.append(float(p[good].sum()))
    return value / len(data) + beta @ beta / 2, grad / len(data) + beta, probabilities


def main():
    path = STUDY / 'fit_selector.py'
    actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    assert actual_hash == EXPECTED
    spec = importlib.util.spec_from_file_location('reviewed_actual_reward_fit', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    rng = np.random.default_rng(20261025)
    races = []
    for k, n in enumerate([7, 10, 13]):
        frame = pd.DataFrame(dict(api_record_id=np.arange(n)+100*k,
            race_id=[f'synthetic{k}']*n, horse_id=[f'{k}:{i}' for i in range(n)],
            horse_number=np.arange(1,n+1), field_n=[n]*n,
            score=rng.normal(size=n), finish_position=rng.permutation(np.arange(1,n+1))))
        rr, summary = module.build_training_races(frame, rng.normal(size=(n, 11)))
        assert summary['positive_sets'] == (n-3)*(n-4)//2
        races.extend(rr)
    a, x, good, groups, n = module.pack_races(races)
    fn = module.make_objective(a, x, good, groups, n)
    data = [(r.base_energy, r.set_features, r.good_mask) for r in races]
    max_error = max_gradient_error = max_value_error = 0.0
    probability_cases = []
    for beta in [np.zeros(11), rng.normal(size=11)*.1, rng.normal(size=11)*.5]:
        value, gradient = fn(beta)
        expected_value, expected_gradient, ps = independent(beta, data)
        probability_cases.append(ps)
        max_value_error = max(max_value_error, abs(value-expected_value))
        max_gradient_error = max(max_gradient_error, float(np.max(np.abs(gradient-expected_gradient))))
        for j in range(11):
            d = np.zeros(11); d[j] = 1e-6
            fd = (fn(beta+d)[0]-fn(beta-d)[0])/2e-6
            max_error = max(max_error, abs(fd-gradient[j]))
        # Policy probabilities/gradients are unchanged by global row permutation.
        order = rng.permutation(len(a))
        v2, g2 = module.make_objective(a[order], x[order], good[order], groups[order], n)(beta)
        assert abs(value-v2) < 1e-12 and np.max(np.abs(gradient-g2)) < 1e-12
    _, ex = module.grouped_logz_and_weights(a, x, groups, n)
    assert ex.shape == (3, 11)
    assert max_error < 1e-8 and max_gradient_error < 1e-12 and max_value_error < 1e-12
    # One action and all-good reward must have constant -1 data loss.
    beta = np.arange(11)*.01
    f5 = module.make_objective(np.array([17.]), rng.normal(size=(1,11)), np.array([True]), np.array([0]), 1)
    loss, grad = f5(beta)
    assert np.isclose(loss, -1+beta@beta/2) and np.allclose(grad, beta)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == EXPECTED
    result = dict(passed=True, synthetic_only=True, new_fits=0, actual_eval_labels_read=False,
                  actual_fit_code_sha256=actual_hash, expected_features_shape=list(ex.shape),
                  actual_code_vs_finite_difference_max_error=float(max_error),
                  actual_code_vs_independent_policy_gradient_max_error=max_gradient_error,
                  actual_code_vs_bruteforce_reward_loss_max_error=float(max_value_error),
                  race_probabilities_tested=probability_cases, full_candidate_positive_mask=True,
                  row_permutation_invariance=True, field_n_5_all_good_control=True,
                  supersedes_failed_version='ROOT_PREFIT_GRADIENT_AUDIT_v1.json')
    with (HERE/'ROOT_REWARD_OBJECTIVE_AUDIT.json').open('x') as f:
        json.dump(result,f,indent=2); f.write('\n')
    print(json.dumps(result,indent=2))


if __name__ == '__main__':
    main()
