"""Call the current fit code on synthetic races and audit its gradient.

Only the source function and synthetic arrays are loaded. No project data,
labels, predictions, or outputs from the fit pipeline are accessed.
"""

from __future__ import annotations

from itertools import combinations
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

import numpy as np


REPO = Path(__file__).resolve().parents[3]
FIT_CODE = REPO / "jeju/research/20261025_top5_reward_learning_v1/fit_selector.py"


def lse(x: np.ndarray) -> float:
    m = float(np.max(x))
    return m + math.log(float(np.exp(x - m).sum(dtype=np.float64)))


def build_synthetic() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, int]:
    rng = np.random.default_rng(6812026)
    base_parts: list[np.ndarray] = []
    feature_parts: list[np.ndarray] = []
    good_parts: list[np.ndarray] = []
    group_parts: list[np.ndarray] = []
    for group, n in enumerate((7, 8, 9)):
        score = rng.normal(size=n)
        score = (score - score.mean()) / score.std(ddof=0)
        runner_phi = rng.normal(size=(n, 11))
        actions = np.asarray(list(combinations(range(n), 5)), dtype=np.int64)
        base_parts.append(score[actions].sum(axis=1, dtype=np.float64))
        feature_parts.append(runner_phi[actions].sum(axis=1, dtype=np.float64))
        top3 = np.zeros(n, dtype=bool)
        top3[[0, 2, n - 1]] = True
        good = top3[actions].sum(axis=1) == 3
        if int(good.sum()) != math.comb(n - 3, 2):
            raise AssertionError("synthetic positive-set count mismatch")
        good_parts.append(good)
        group_parts.append(np.full(len(actions), group, dtype=np.int32))
    return (
        np.concatenate(base_parts),
        np.concatenate(feature_parts, axis=0),
        np.concatenate(good_parts),
        np.concatenate(group_parts),
        3,
    )


def independent_objective(
    base: np.ndarray,
    features: np.ndarray,
    good: np.ndarray,
    groups: np.ndarray,
    race_count: int,
    beta: np.ndarray,
    lam: float,
) -> tuple[float, np.ndarray, list[float]]:
    energy = base + features @ beta
    per_race_probability: list[float] = []
    gradient_sum = np.zeros_like(beta)
    for race in range(race_count):
        rows = groups == race
        e = energy[rows]
        f = features[rows]
        g = good[rows]
        p = math.exp(lse(e[g]) - lse(e))
        w_all = np.exp(e - lse(e))
        e_good = e[g]
        f_good = f[g]
        w_good = np.exp(e_good - lse(e_good))
        expected_all = w_all @ f
        expected_good = w_good @ f_good
        gradient_sum += 2.0 * p * (expected_all - expected_good)
        per_race_probability.append(p)
    loss = float(
        np.mean(1.0 - 2.0 * np.asarray(per_race_probability))
        + 0.5 * lam * (beta @ beta)
    )
    return loss, gradient_sum / race_count + lam * beta, per_race_probability


def run() -> dict[str, object]:
    source = FIT_CODE.read_bytes()
    source_hash = hashlib.sha256(source).hexdigest()
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location("reward_fit_under_review", FIT_CODE)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load fixed fit source")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    base, features, good, groups, race_count = build_synthetic()
    objective = module.make_objective(base, features, good, groups, race_count)
    beta = np.linspace(-0.16, 0.19, features.shape[1], dtype=np.float64)
    actual_loss, actual_gradient = objective(beta)
    expected_loss, expected_gradient, probabilities = independent_objective(
        base, features, good, groups, race_count, beta, float(module.LAMBDA)
    )

    epsilon = 1e-6
    numeric_gradient = np.empty_like(beta)
    for j in range(len(beta)):
        delta = np.zeros_like(beta)
        delta[j] = epsilon
        numeric_gradient[j] = (
            objective(beta + delta)[0] - objective(beta - delta)[0]
        ) / (2.0 * epsilon)

    loss_error = abs(float(actual_loss) - expected_loss)
    independent_gradient_error = float(np.max(np.abs(actual_gradient - expected_gradient)))
    finite_difference_error = float(np.max(np.abs(actual_gradient - numeric_gradient)))
    passed = (
        loss_error < 1e-12
        and independent_gradient_error < 1e-9
        and finite_difference_error < 1e-7
    )
    return {
        "status": "PASS" if passed else "FAIL",
        "fit_code_sha256": source_hash,
        "synthetic_races": race_count,
        "synthetic_actions": int(len(base)),
        "synthetic_positive_actions": int(good.sum()),
        "p_good_by_race": probabilities,
        "actual_loss": float(actual_loss),
        "independent_loss": expected_loss,
        "absolute_loss_error": loss_error,
        "actual_gradient_shape": list(actual_gradient.shape),
        "independent_gradient_max_abs_error": independent_gradient_error,
        "finite_difference_max_abs_error": finite_difference_error,
        "gradient_matches_independent_formula": independent_gradient_error < 1e-9,
        "gradient_matches_finite_difference": finite_difference_error < 1e-7,
        "reads_project_data_or_outcomes": False,
    }


if __name__ == "__main__":
    print(json.dumps(run(), sort_keys=True, indent=2))
