"""Independent rank-stage probability reference; no experiment imports or fits."""
import importlib.util
import math
import sys
from pathlib import Path

import numpy as np

sys.dont_write_bytecode = True
PREVIOUS = Path(__file__).resolve().parents[2] / '20261022_joint_wager_baseline_v1/supervisor/math_reference.py'
spec = importlib.util.spec_from_file_location('_previous_supervisor_math', PREVIOUS)
previous = importlib.util.module_from_spec(spec)
spec.loader.exec_module(previous)
aggregate = previous.aggregate
score_events = previous.score_events
winners = previous.winners


def reference_distribution(scores, temperatures):
    """Expand all hypothetical prefixes, with explicit remaining choice sets."""
    s = np.asarray(scores, dtype=float)
    t = np.asarray(temperatures, dtype=float)
    assert t.shape == (3,) and np.isfinite(t).all() and (t > 0).all()
    assert s.ndim == 1 and len(s) >= 3 and np.isfinite(s).all()
    prefixes = {(): 1.0}
    for temperature in t:
        expanded = {}
        for prefix, prefix_probability in prefixes.items():
            remaining = [h for h in range(len(s)) if h not in prefix]
            u = s[remaining] / temperature
            weights = np.exp(u - max(u))
            denominator = math.fsum(weights)
            for horse, weight in zip(remaining, weights):
                expanded[prefix + (horse,)] = float(prefix_probability * weight / denominator)
        prefixes = expanded
    assert len(prefixes) == len(s) * (len(s) - 1) * (len(s) - 2)
    assert abs(math.fsum(prefixes.values()) - 1) < 1e-12
    return prefixes


def stage_derivatives(calibration_races, temperatures):
    """Evaluate the fixed fit's convex first/second derivatives in beta=1/T."""
    rows = []
    for scores, actual in calibration_races:
        scores = np.asarray(scores, dtype=float)
        remaining = list(range(len(scores)))
        stages = []
        for chosen, temperature in zip(actual, temperatures):
            s = scores[remaining]
            u = s / temperature
            maximum = max(u)
            weights = np.exp(u - maximum)
            denominator = math.fsum(weights)
            probability = weights / denominator
            mean = float(probability @ s)
            loss = maximum + math.log(denominator) - scores[chosen] / temperature
            gradient = mean - scores[chosen]
            curvature = float(probability @ ((s - mean) ** 2))
            stages.append((loss, gradient, curvature))
            remaining.remove(chosen)
        rows.append(stages)
    means = np.mean(np.asarray(rows), axis=0)
    return [dict(stage=i + 1, nll=float(row[0]), gradient_inverse_t=float(row[1]),
                 hessian_inverse_t=float(row[2])) for i, row in enumerate(means)]


def stable_selection(probabilities, tolerance=1e-12):
    maximum = max(probabilities.values())
    selected = min(key for key, p in probabilities.items() if p >= maximum - tolerance)
    return selected, probabilities[selected]


def synthetic():
    max_common_error = 0.0
    for n in (5, 7, 8, 10):
        scores = np.linspace(-1.5, 2, n)
        for common in (1.0, 1.1837152381349905):
            joint = reference_distribution(scores, [common] * 3)
            prior = previous.reference_distribution(scores, common)
            max_common_error = max(max_common_error, max(abs(joint[k] - prior[k]) for k in joint))
        base = reference_distribution(scores, [.8, 1.4, 2.0])
        shifted = reference_distribution(scores + 1000, [.8, 1.4, 2.0])
        assert max(abs(base[k] - shifted[k]) for k in base) < 1e-12
        plc = 2 if n < 8 else 3
        maps, ranks = aggregate(base, n, plc)
        u = scores / .8
        weights = np.exp(u - max(u))
        assert np.allclose(ranks[:, 0], weights / math.fsum(weights), atol=1e-12, rtol=0)
        alt, _ = aggregate(reference_distribution(scores, [.8, 1.4, .45]), n, plc)
        for pool in ('WIN', 'EXA', 'QNL'):
            assert max(abs(maps[pool][key] - alt[pool][key]) for key in maps[pool]) < 1e-12
    assert max_common_error < 1e-12
    scores = np.array([.2, .1, 0., -.1, -.2])
    q = reference_distribution(scores, [4., .35, 2.])
    assert q[(1, 0, 2)] > q[(0, 1, 2)]
    key, probability = stable_selection({(1,): .3, (0,): .3 - 5e-13})
    assert key == (0,) and probability == .3 - 5e-13
    return dict(passed=True, common_temperature_max_error=max_common_error,
                all_pool_and_marginal_sums=True, shift_invariance=True,
                third_stage_does_not_change_first_two_marginals=True,
                ordered_preference_can_reverse_within_bounds=True,
                ordered_swap_ratio=float(q[(1, 0, 2)] / q[(0, 1, 2)]),
                numerical_tie_selection_uses_selected_probability=True)


if __name__ == '__main__':
    import json
    print(json.dumps(synthetic(), indent=2))
