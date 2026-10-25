"""Independent synthetic verification of the exact Top5 reward objective.

This file intentionally contains no project/data imports and reads no source
files. It enumerates every five-set for small synthetic races and checks the
analytic expected-reward gradient by central finite differences.
"""

from __future__ import annotations

from itertools import combinations
import math

import numpy as np


LAMBDA = 1.0


def race_arrays(
    score_z: np.ndarray, runner_phi: np.ndarray, top3: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    n = len(score_z)
    actions = np.asarray(list(combinations(range(n), 5)), dtype=np.int64)
    base = score_z[actions].sum(axis=1, dtype=np.float64)
    phi = runner_phi[actions].sum(axis=1, dtype=np.float64)
    good = top3[actions].sum(axis=1) == 3
    if int(top3.sum()) != 3:
        raise ValueError("synthetic training race must have exactly three Top3 labels")
    if int(good.sum()) != math.comb(n - 3, 2):
        raise AssertionError("positive-set count is not C(N-3, 2)")
    return base, phi, good


def logsumexp(values: np.ndarray) -> float:
    maximum = float(np.max(values))
    return maximum + math.log(float(np.exp(values - maximum).sum(dtype=np.float64)))


def race_probability_and_moments(
    base: np.ndarray, phi: np.ndarray, good: np.ndarray, beta: np.ndarray
) -> tuple[float, np.ndarray, np.ndarray]:
    energy = base + phi @ beta
    logz_all = logsumexp(energy)
    logz_good = logsumexp(energy[good])
    p_good = math.exp(logz_good - logz_all)
    weights_all = np.exp(energy - logz_all)
    weights_good = np.exp(energy[good] - logz_good)
    expected_all = weights_all @ phi
    expected_good = weights_good @ phi[good]
    return p_good, expected_all, expected_good


def objective_and_gradient(
    races: list[tuple[np.ndarray, np.ndarray, np.ndarray]], beta: np.ndarray
) -> tuple[float, np.ndarray, np.ndarray]:
    p_values = []
    gradient = np.zeros_like(beta, dtype=np.float64)
    for base, phi, good in races:
        p_good, expected_all, expected_good = race_probability_and_moments(
            base, phi, good, beta
        )
        p_values.append(p_good)
        gradient += 2.0 * p_good * (expected_all - expected_good)
    p = np.asarray(p_values, dtype=np.float64)
    objective = float(np.mean(1.0 - 2.0 * p) + 0.5 * LAMBDA * (beta @ beta))
    gradient = gradient / len(races) + LAMBDA * beta
    return objective, gradient, p


def run() -> dict[str, float | int | bool]:
    # Two races with different rosters and nonconstant score/input signals.
    races = []
    for n, offset in ((7, 0.0), (8, 0.35)):
        score = np.linspace(-1.2, 1.4, n, dtype=np.float64)
        score = (score - score.mean()) / score.std(ddof=0)
        phase = np.arange(n, dtype=np.float64) + offset
        runner_phi = np.column_stack(
            [np.sin(phase), np.cos(phase * 0.7), (phase - phase.mean()) / n]
        )
        top3 = np.zeros(n, dtype=bool)
        top3[[0, 2, 4]] = True
        races.append(race_arrays(score, runner_phi, top3))

    beta = np.array([0.17, -0.23, 0.08], dtype=np.float64)
    value, analytic, p_values = objective_and_gradient(races, beta)
    reward_identity_error = 0.0
    for base, phi, good in races:
        energy = base + phi @ beta
        logz = logsumexp(energy)
        policy = np.exp(energy - logz)
        realized_reward = np.where(good, 1.0, -1.0)
        p_good = float(policy[good].sum(dtype=np.float64))
        direct_expected_reward = float(policy @ realized_reward)
        reward_identity_error = max(
            reward_identity_error,
            abs(direct_expected_reward - (2.0 * p_good - 1.0)),
        )
    epsilon = 1.0e-6
    numeric = np.empty_like(beta)
    for j in range(len(beta)):
        step = np.zeros_like(beta)
        step[j] = epsilon
        plus = objective_and_gradient(races, beta + step)[0]
        minus = objective_and_gradient(races, beta - step)[0]
        numeric[j] = (plus - minus) / (2.0 * epsilon)

    max_abs_error = float(np.max(np.abs(analytic - numeric)))
    if max_abs_error >= 1.0e-7:
        raise AssertionError(f"finite-difference gradient mismatch: {max_abs_error}")
    if reward_identity_error >= 1.0e-14:
        raise AssertionError(f"expected reward identity mismatch: {reward_identity_error}")
    if not np.all((p_values >= 0.0) & (p_values <= 1.0)):
        raise AssertionError("Pgood outside [0, 1]")
    rewards = np.where(np.concatenate([r[2] for r in races]), 1.0, -1.0)
    if not np.array_equal(np.unique(rewards), np.array([-1.0, 1.0])):
        raise AssertionError("exact-set reward support changed")

    return {
        "synthetic_races": len(races),
        "action_counts": sum(len(r[0]) for r in races),
        "positive_action_counts": sum(int(r[2].sum()) for r in races),
        "expected_reward_objective": value,
        "p_good_min": float(p_values.min()),
        "p_good_max": float(p_values.max()),
        "finite_difference_max_abs_gradient_error": max_abs_error,
        "direct_expected_reward_identity_error": reward_identity_error,
        "gradient_check_passed": True,
    }


if __name__ == "__main__":
    import json

    print(json.dumps(run(), sort_keys=True, indent=2))
