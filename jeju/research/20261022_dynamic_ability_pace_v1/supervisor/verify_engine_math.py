"""Cross-check the worker's formulas against the independent supervisor reference.

Synthetic inputs only. No training or calibration is invoked.
"""
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ENGINE = HERE.parent/'experiment/dynamic_ability_pace.py'
spec = importlib.util.spec_from_file_location('_worker_math_under_review', ENGINE)
worker = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = worker
spec.loader.exec_module(worker)
from math_reference import aggregate, distribution, mixture, rank_loss_derivatives, synthetic


def run():
    report = synthetic()
    rng = np.random.default_rng(70622)
    rows, references = [], []
    for n in (5, 7, 8, 12):
        score = rng.normal(size=n)
        ranks = rng.permutation(n)+1
        actual = np.argsort(ranks)[:3]
        rows.append((score, ranks))
        references.append(rank_loss_derivatives(score, actual))
    n_races = len(rows)
    scores = np.concatenate([r[0] for r in rows])
    ranks = np.concatenate([r[1] for r in rows])
    groups = [len(r[0]) for r in rows]
    value, grad, hess = worker.ordered_top3_pl_nll_grad_hess(scores, ranks, groups)
    expected_grad = np.concatenate([r[1] for r in references])/n_races
    expected_hess = np.concatenate([np.diag(r[2]) for r in references])/n_races
    assert abs(value-np.mean([r[0] for r in references])) < 1e-12
    assert np.max(np.abs(grad-expected_grad)) < 1e-12
    assert np.max(np.abs(hess-expected_hess)) < 1e-12

    class DatasetStub:
        def get_label(self): return ranks
        def get_group(self): return np.array(groups)

    cg, ch = worker.lightgbm_ordered_top3_objective(scores, DatasetStub())
    assert np.max(np.abs(cg-expected_grad*n_races)) < 1e-12, 'LightGBM must use summed race losses'
    assert np.max(np.abs(ch-np.maximum(expected_hess*n_races, 1e-6))) < 1e-12
    closure = worker.make_lightgbm_ordered_top3_objective(ranks, groups)
    gg, hh = closure(scores, DatasetStub())
    assert np.max(np.abs(gg-cg)) < 1e-12 and np.max(np.abs(hh-ch)) < 1e-12
    extreme = np.concatenate([np.linspace(-100, 100, n) for n in groups])
    _, eg, eh = worker.ordered_top3_pl_nll_grad_hess(extreme, ranks, groups)
    cg, ch = closure(extreme, DatasetStub())
    assert np.allclose(cg, eg*n_races, atol=1e-12, rtol=0)
    assert np.allclose(ch, np.maximum(eh*n_races, 1e-6), atol=1e-12, rtol=0)
    assert np.any(ch == 1e-6)
    max_pool_error = 0.
    for score, ranks in rows:
        n = len(score); numbers = np.arange(1, n+1)
        plc = 2 if n < 8 else 3
        other = score[::-1]*.8
        for q in (0., .23, 1.):
            maps, _, mass = worker.probability_maps_from_scenarios([score, other], [1-q, q], numbers, plc)
            rm, _ = aggregate(mixture(score, other, q), n, plc)
            assert abs(mass-1) < 1e-12
            for pool, tickets in rm.items():
                for key, p in tickets.items():
                    e = abs(maps[pool][tuple(i+1 for i in key)]-p)
                    max_pool_error = max(max_pool_error, e)
    assert max_pool_error < 1e-12
    # Conditional expert derivatives are a linear map of the rank derivatives.
    gamma = np.array([.2, -.4, .1, .3]); fitted_rows = []
    wanted_loss, wanted_grad, wanted_hess = 0., np.zeros(4), np.zeros((4, 4))
    for j, (score, rank) in enumerate(rows):
        pe, ph = rng.uniform(size=(2, len(score))); z = j % 2
        x = np.array([pe-pe.mean(), ph-ph.mean(), z*(pe-pe.mean()), z*(ph-ph.mean())]).T
        l, g, h = rank_loss_derivatives(score+x@gamma, np.argsort(rank)[:3])
        wanted_loss += l; wanted_grad += x.T@g; wanted_hess += x.T@h@x
        fitted_rows.append(dict(a=score, ranks=rank, z=z, p_early=pe, p_recovery=ph))
    l, g, h = worker.conditional_gamma_objective_grad_hess(gamma, fitted_rows)
    assert abs(l-(wanted_loss/n_races+.005*(gamma@gamma))) < 1e-12
    assert np.max(np.abs(g-(wanted_grad/n_races+.01*gamma))) < 1e-12
    assert np.max(np.abs(h-(wanted_hess/n_races+.01*np.eye(4)))) < 1e-12
    report.update(engine_sha256=hashlib.sha256(ENGINE.read_bytes()).hexdigest(),
                  mean_loss_and_summed_training_gradients_match=True,
                  conditional_gamma_gradient_and_full_hessian_match=True,
                  max_seven_pool_mixture_probability_error=max_pool_error)
    return report


if __name__ == '__main__':
    result = run()
    print(json.dumps(result, indent=2))
