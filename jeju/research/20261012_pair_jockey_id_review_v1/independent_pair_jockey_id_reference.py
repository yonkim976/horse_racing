"""Small independent extension of the frozen pair-jockey numerical reference.

This module adds only the H1-only categorical pair columns and a dimension-
agnostic BCE/ridge gradient. It contains no optimizer and performs no work at
import time. The existing basic-review reference remains authoritative for the
unchanged 20 style bases and rolling 21st basis.
"""

from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np


ROOT = Path("/Users/kimyongjin/Desktop/horse_racing").resolve()
BASIC_REFERENCE_PATH = ROOT / (
    "jeju/research/20261012_pair_jockey_basic_review_v1/independent_jockey_reference.py"
)


def _load_basic_reference():
    spec = importlib.util.spec_from_file_location("frozen_basic_pair_jockey_reference_for_id", BASIC_REFERENCE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load frozen independent basic reference: {BASIC_REFERENCE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


basic = _load_basic_reference()
ref = basic.ref


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ref.ReproductionError(message)


def enumerated_category_moments(
    jockey_ids_by_race: Sequence[Mapping[int, str]],
    pairs_by_race: Sequence[Sequence[tuple[int, int]]],
    vocabulary: Sequence[str],
) -> dict[str, Any]:
    """Recompute race-equal μ, π and σ by enumerating every unordered pair."""
    vocab = tuple(map(str, vocabulary))
    require(len(vocab) > 0 and len(set(vocab)) == len(vocab), "invalid H1 jockey vocabulary")
    require(len(jockey_ids_by_race) == len(pairs_by_race) > 0, "H1 category race counts differ")
    index = {jockey_id: column for column, jockey_id in enumerate(vocab)}
    race_means: list[np.ndarray] = []
    race_seconds: list[np.ndarray] = []
    pair_total = 0
    for race_index, (id_by_horse, pairs) in enumerate(zip(jockey_ids_by_race, pairs_by_race, strict=True)):
        require(bool(pairs), f"empty unordered-pair list in H1 race {race_index}")
        values = np.zeros((len(pairs), len(vocab)), dtype=float)
        for row_index, (left, right) in enumerate(pairs):
            require(left != right and left in id_by_horse and right in id_by_horse,
                    f"invalid pair roster in H1 race {race_index}")
            for horse in (left, right):
                jockey_id = str(id_by_horse[horse])
                require(jockey_id in index, f"H1 race {race_index} has ID outside H1 vocabulary")
                values[row_index, index[jockey_id]] += 1.0
        race_means.append(np.asarray([
            math.fsum(map(float, values[:, column])) / len(values)
            for column in range(len(vocab))
        ], dtype=float))
        race_seconds.append(np.asarray([
            math.fsum(float(value) * float(value) for value in values[:, column]) / len(values)
            for column in range(len(vocab))
        ], dtype=float))
        pair_total += len(pairs)
    mu = np.asarray([
        math.fsum(float(row[column]) for row in race_means) / len(race_means)
        for column in range(len(vocab))
    ], dtype=float)
    second = np.asarray([
        math.fsum(float(row[column]) for row in race_seconds) / len(race_seconds)
        for column in range(len(vocab))
    ], dtype=float)
    variance = second - mu * mu
    require(np.isfinite(mu).all() and np.isfinite(variance).all()
            and (variance >= -1e-12).all(), "invalid independent category moments")
    sigma = np.sqrt(np.maximum(variance, 0.0))
    pi = mu / 2.0
    require(abs(math.fsum(map(float, pi)) - 1.0) <= 1e-12, "H1 category exposure weights do not sum to one")
    return {
        "vocabulary": vocab, "mu": mu, "pi": pi, "sigma": sigma,
        "degenerate": tuple(bool(value <= 1e-12) for value in sigma),
        "h1_races": len(race_means), "h1_pairs": pair_total,
    }


def categorical_pair_matrix(
    pairs: Sequence[tuple[int, int]],
    jockey_id_by_horse: Mapping[int, str],
    vocabulary: Sequence[str],
    pi: Sequence[float],
    sigma: Sequence[float],
) -> np.ndarray:
    """Build W=(u-K*pi)/sigma; an unseen runner adds exactly zero effect."""
    vocab = tuple(map(str, vocabulary))
    weights = np.asarray(pi, dtype=float)
    scales = np.asarray(sigma, dtype=float)
    require(len(weights) == len(scales) == len(vocab), "categorical moment dimensions differ")
    require(np.isfinite(weights).all() and np.isfinite(scales).all(), "non-finite categorical moments")
    category_index = {jockey_id: column for column, jockey_id in enumerate(vocab)}
    output = np.zeros((len(pairs), len(vocab)), dtype=float)
    active = scales > 1e-12
    for row_index, (left, right) in enumerate(pairs):
        use = np.zeros(len(vocab), dtype=float)
        known = 0
        for horse in (left, right):
            require(horse in jockey_id_by_horse, "pair horse is missing event jockey ID")
            column = category_index.get(str(jockey_id_by_horse[horse]))
            if column is not None:
                use[column] += 1.0
                known += 1
        centered = use - known * weights
        output[row_index, active] = centered[active] / scales[active]
    require(np.isfinite(output).all(), "non-finite independent categorical pair design")
    return output


def centered_runner_effects(
    theta: Sequence[float], pi: Sequence[float], sigma: Sequence[float]
) -> np.ndarray:
    """Convert standardized θ to H1 exposure-weighted mean-zero known-ID α."""
    coefficient = np.asarray(theta, dtype=float)
    weights = np.asarray(pi, dtype=float)
    scales = np.asarray(sigma, dtype=float)
    require(coefficient.shape == weights.shape == scales.shape, "θ/π/σ dimensions differ")
    require(np.isfinite(coefficient).all() and np.isfinite(weights).all()
            and np.isfinite(scales).all(), "non-finite θ/π/σ")
    alpha = np.zeros_like(coefficient)
    active = scales > 1e-12
    alpha[active] = coefficient[active] / scales[active]
    alpha[active] -= math.fsum(
        float(weights[index] * alpha[index]) for index in range(len(alpha)) if active[index]
    )
    return alpha


def standardize_60d_basis(
    raw_20_by_race: Sequence[np.ndarray],
    rolling_pair_by_race: Sequence[np.ndarray],
    jockey_ids_by_race: Sequence[Mapping[int, str]],
    pairs_by_race: Sequence[Sequence[tuple[int, int]]],
    frozen_20_moments,
    rolling_moments: Mapping[str, Any],
    category_moments: Mapping[str, Any],
) -> list[np.ndarray]:
    """Reuse the prior frozen 21-column transform, then append category columns."""
    require(
        len(raw_20_by_race) == len(rolling_pair_by_race)
        == len(jockey_ids_by_race) == len(pairs_by_race) > 0,
        "race counts differ in 60-column basis",
    )
    vocab = tuple(map(str, category_moments["vocabulary"]))
    output = []
    frozen_21 = basic.standardize_21d_basis(
        raw_20_by_race, rolling_pair_by_race, frozen_20_moments, rolling_moments,
    )
    for race_index, (x21, id_map, pairs) in enumerate(zip(
        frozen_21, jockey_ids_by_race, pairs_by_race, strict=True
    )):
        category = categorical_pair_matrix(
            pairs, id_map, vocab, category_moments["pi"], category_moments["sigma"],
        )
        combined = np.column_stack((x21, category))
        require(combined.shape == (len(pairs), 21 + len(vocab)),
                f"invalid independent 60-column basis in race {race_index}")
        require(np.array_equal(combined[:, :21], x21),
                f"frozen first 21 columns changed in race {race_index}")
        output.append(combined)
    return output


def h1_objective_gradient(
    beta: Sequence[float],
    standardized_basis_by_race: Sequence[np.ndarray],
    p0_by_race: Sequence[np.ndarray],
    labels_by_race: Sequence[np.ndarray],
    ridge_lambda: float = 1.0,
) -> tuple[float, np.ndarray]:
    """Generic-dimensional race-equal BCE + λ/2||β||² and its gradient."""
    coefficient = np.asarray(beta, dtype=float)
    require(coefficient.ndim == 1 and coefficient.size > 0 and np.isfinite(coefficient).all(),
            "invalid saved coefficient vector")
    require(math.isfinite(float(ridge_lambda)) and ridge_lambda >= 0.0, "invalid frozen ridge value")
    require(
        len(standardized_basis_by_race) == len(p0_by_race)
        == len(labels_by_race) > 0,
        "H1 race input counts differ",
    )
    race_loss: list[float] = []
    gradient = float(ridge_lambda) * coefficient.copy()
    n_races = len(standardized_basis_by_race)
    for race_index, (basis, prior, labels) in enumerate(zip(
        standardized_basis_by_race, p0_by_race, labels_by_race, strict=True
    )):
        x = np.asarray(basis, dtype=float)
        p = np.asarray(prior, dtype=float)
        y = np.asarray(labels, dtype=float)
        require(x.ndim == 2 and x.shape[1] == len(coefficient) and len(x) > 0,
                f"invalid H1 basis race {race_index}")
        require(x.shape[0] == len(p) == len(y), f"H1 pair count differs in race {race_index}")
        require(np.isfinite(x).all() and np.isfinite(p).all()
                and np.isfinite(y).all(), f"non-finite H1 race {race_index}")
        require(((p > 0.0) & (p < 1.0)).all(), f"H1 prior outside (0,1) in race {race_index}")
        require(((y == 0.0) | (y == 1.0)).all(), f"non-binary H1 pair label in race {race_index}")
        logits = ref.logit(p) + x @ coefficient
        residual = ref.sigmoid(logits) - y
        losses = ref.bce_from_logits(logits, y)
        race_loss.append(math.fsum(map(float, losses)) / len(losses))
        gradient += (x.T @ residual) / (n_races * len(x))
    objective = math.fsum(race_loss) / n_races + 0.5 * float(ridge_lambda) * float(
        np.dot(coefficient, coefficient)
    )
    require(math.isfinite(objective) and np.isfinite(gradient).all(),
            "non-finite independent H1 objective/gradient")
    return float(objective), gradient


def h2_objective_gradient(
    parameters: Sequence[float],
    raw_logits_by_race: Sequence[np.ndarray],
    labels_by_race: Sequence[np.ndarray],
) -> tuple[float, np.ndarray]:
    """Reuse the frozen independent positive-slope Platt objective."""
    return basic.h2_objective_gradient(parameters, raw_logits_by_race, labels_by_race)


def predict_race_60d(
    horse_numbers: Sequence[int],
    scores: Sequence[float],
    runner_values: Mapping[str, Sequence[float]],
    rolling_value_by_horse: Mapping[int, float],
    jockey_id_by_horse: Mapping[int, str],
    runner_moments,
    frozen_20_moments,
    rolling_moments: Mapping[str, Any],
    category_moments: Mapping[str, Any],
    beta: Sequence[float],
    candidate_platt: Sequence[float],
) -> dict[str, Any]:
    """Wrap the frozen 21-column predictor and add only independently built ID columns."""
    coefficient = np.asarray(beta, dtype=float)
    vocab = tuple(map(str, category_moments["vocabulary"]))
    require(coefficient.shape == (21 + len(vocab),) and np.isfinite(coefficient).all(),
            "invalid saved 60-column coefficient vector")
    baseline21 = basic.predict_race_21d(
        horse_numbers, scores, runner_values, rolling_value_by_horse,
        runner_moments, frozen_20_moments, rolling_moments,
        coefficient[:21], candidate_platt,
    )
    category = categorical_pair_matrix(
        baseline21["pairs"], jockey_id_by_horse, vocab,
        category_moments["pi"], category_moments["sigma"],
    )
    x60 = np.column_stack((baseline21["standardized_basis_21"], category))
    require(np.array_equal(x60[:, :21], baseline21["standardized_basis_21"]),
            "frozen first 21 prediction columns changed")
    eta = ref.logit(baseline21["p0"]) + x60 @ coefficient
    a, b = map(float, candidate_platt)
    require(math.isfinite(a) and math.isfinite(b) and b > 0.0,
            "invalid saved candidate positive-slope Platt map")
    selected = ref.choose_pair(baseline21["pairs"], eta)
    calibrated_selected = ref.choose_pair(baseline21["pairs"], a + b * eta)
    require(selected == calibrated_selected,
            "positive-slope category candidate calibration changed pair selector")
    return {
        "pairs": baseline21["pairs"], "p0": baseline21["p0"], "q0": baseline21["q0"],
        "standardized_basis_60": x60, "eta": eta,
        "candidate_raw_probability": ref.sigmoid(eta),
        "candidate_calibrated_probability": ref.sigmoid(a + b * eta),
        "selected_candidate": selected,
    }
