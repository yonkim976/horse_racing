"""Independent post-fit math for the single 365-day jockey pair input.

This module reuses the prior study's independent numerical reference for the
unchanged 20 bases. It imports no candidate fit or prediction implementation,
contains no optimizer, and performs no work at import time. Call data-dependent
helpers only after the root-approved fit/prediction receipts are available.
"""

from __future__ import annotations

import importlib.util
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np


ROOT = Path("/Users/kimyongjin/Desktop/horse_racing").resolve()
OLD_REFERENCE = ROOT / "jeju/research/20261011_pair_top3_direct_review_v1/independent_reference.py"
SCHEDULE_PATH = ROOT / "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy"
SCHEDULE_RECEIPT_PATH = ROOT / "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.json"
EXPECTED_SCHEDULE_SHA256 = "d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd"


def _load_old_reference():
    spec = importlib.util.spec_from_file_location("pair_top3_independent_reference_for_jockey", OLD_REFERENCE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load frozen independent reference: {OLD_REFERENCE}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ref = _load_old_reference()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ref.ReproductionError(message)


def pair_jockey_sums(
    pairs: Sequence[tuple[int, int]],
    jockey_value_by_horse: Mapping[int, float],
) -> np.ndarray:
    """Return symmetric d_i+d_j values in the already-canonical pair order."""
    values = {int(key): float(value) for key, value in jockey_value_by_horse.items()}
    require(bool(pairs) and all(math.isfinite(v) for v in values.values()), "invalid runner jockey values")
    out = np.asarray([values[int(a)] + values[int(b)] for a, b in pairs], dtype=float)
    require(np.isfinite(out).all(), "non-finite symmetric jockey pair sum")
    reverse = np.asarray([values[int(b)] + values[int(a)] for a, b in pairs], dtype=float)
    require(np.array_equal(out, reverse), "jockey pair input is not symmetric")
    return out


def fit_jockey_pair_moments(per_race_values: Sequence[Sequence[float]]) -> dict[str, Any]:
    """Recompute H1-only race-equal moments for the 21st scalar basis."""
    arrays = [np.asarray(row, dtype=float) for row in per_race_values]
    require(bool(arrays) and all(a.ndim == 1 and len(a) > 0 for a in arrays), "empty/invalid H1 jockey pair arrays")
    require(all(np.isfinite(a).all() for a in arrays), "non-finite H1 jockey pair values")
    race_means = [math.fsum(map(float, values)) / len(values) for values in arrays]
    mean = math.fsum(race_means) / len(race_means)
    race_variances = [math.fsum((float(value) - mean) ** 2 for value in values) / len(values) for values in arrays]
    variance = math.fsum(race_variances) / len(race_variances)
    require(math.isfinite(mean) and math.isfinite(variance) and variance >= 0.0, "invalid independent H1 jockey moments")
    scale = math.sqrt(variance)
    degenerate = scale <= 1e-12
    return {
        "mean": 0.0 if degenerate else mean,
        "scale": 1.0 if degenerate else scale,
        "degenerate": degenerate,
        "support_weight": float(len(arrays)),
        "standardization_scope": "H1-only race-equal pair rows, race total weight 1",
    }


def standardize_21d_basis(
    raw_20_by_race: Sequence[np.ndarray],
    jockey_sum_by_race: Sequence[np.ndarray],
    frozen_20d_moments,
    jockey_moments: Mapping[str, Any],
) -> list[np.ndarray]:
    """Apply frozen 20-d transforms verbatim and H1 moments to column 21."""
    require(len(raw_20_by_race) == len(jockey_sum_by_race) > 0, "race count differs in 21-d transform")
    result: list[np.ndarray] = []
    for raw20, jockey_raw in zip(raw_20_by_race, jockey_sum_by_race, strict=True):
        raw = np.asarray(raw20, dtype=float)
        rider = np.asarray(jockey_raw, dtype=float)
        require(raw.ndim == 2 and raw.shape[1] == 20 and raw.shape[0] == len(rider), "21-d raw basis shape mismatch")
        x20 = ref.apply_pair_moments(raw, frozen_20d_moments)
        if bool(jockey_moments["degenerate"]):
            rider_z = np.zeros(len(rider), dtype=float)
        else:
            rider_z = (rider - float(jockey_moments["mean"])) / float(jockey_moments["scale"])
        x21 = np.column_stack((x20, rider_z))
        require(x21.shape == (len(rider), 21) and np.isfinite(x21).all(), "invalid independent 21-d standardized basis")
        require(np.array_equal(x21[:, :20], x20), "frozen 20 standardized columns changed")
        result.append(x21)
    return result


def h1_objective_gradient_21(
    beta: Sequence[float],
    standardized_basis_by_race: Sequence[np.ndarray],
    p0_by_race: Sequence[np.ndarray],
    labels_by_race: Sequence[np.ndarray],
) -> tuple[float, np.ndarray]:
    """Independent race-equal BCE + lambda=1 ridge value/gradient at saved beta."""
    coefficient = np.asarray(beta, dtype=float)
    require(coefficient.shape == (21,) and np.isfinite(coefficient).all(), "invalid stored 21-d H1 coefficients")
    require(len(standardized_basis_by_race) == len(p0_by_race) == len(labels_by_race) > 0,
            "H1 race input counts differ")
    objective_parts: list[float] = []
    gradient = coefficient.copy()  # unit ridge; no intercept
    n_races = len(standardized_basis_by_race)
    for index, (basis, prior, labels) in enumerate(zip(
        standardized_basis_by_race, p0_by_race, labels_by_race, strict=True
    )):
        x = np.asarray(basis, dtype=float)
        p = np.asarray(prior, dtype=float)
        y = np.asarray(labels, dtype=float)
        require(x.ndim == 2 and x.shape[1] == 21 and len(x) > 0, f"invalid H1 basis race {index}")
        require(x.shape[0] == len(p) == len(y), f"H1 pair count differs in race {index}")
        require(np.isfinite(x).all() and np.isfinite(p).all() and np.isfinite(y).all(), f"non-finite H1 race {index}")
        require(((p > 0.0) & (p < 1.0)).all(), f"H1 prior outside (0,1) in race {index}")
        require(((y == 0.0) | (y == 1.0)).all(), f"non-binary H1 label in race {index}")
        logits = ref.logit(p) + x @ coefficient
        residual = ref.sigmoid(logits) - y
        objective_parts.append(float(np.mean(ref.bce_from_logits(logits, y))))
        gradient += (x.T @ residual) / (n_races * len(x))
    objective = float(np.mean(objective_parts) + 0.5 * np.dot(coefficient, coefficient))
    require(math.isfinite(objective) and np.isfinite(gradient).all(), "non-finite independent H1 objective/gradient")
    return objective, gradient


def h2_objective_gradient(
    parameters: Sequence[float],
    raw_logits_by_race: Sequence[np.ndarray],
    labels_by_race: Sequence[np.ndarray],
) -> tuple[float, np.ndarray]:
    """Use the existing independent positive-slope Platt BCE/gradient helper."""
    theta = np.asarray(parameters, dtype=float)
    require(theta.shape == (2,) and math.isfinite(float(theta[1])) and theta[1] > 0.0,
            "invalid candidate H2 positive-slope Platt parameters")
    return ref.platt_objective_gradient(theta, raw_logits_by_race, labels_by_race)


def predict_race_21d(
    horse_numbers: Sequence[int],
    scores: Sequence[float],
    runner_values: Mapping[str, Sequence[float]],
    jockey_value_by_horse: Mapping[int, float],
    runner_moments,
    frozen_20d_moments,
    jockey_moments: Mapping[str, Any],
    beta: Sequence[float],
    candidate_platt: Sequence[float],
) -> dict[str, Any]:
    """Independently reconstruct all pairs, logits, calibrated probabilities and pick."""
    coefficient = np.asarray(beta, dtype=float)
    require(coefficient.shape == (21,) and np.isfinite(coefficient).all(), "invalid stored 21-d coefficients")
    a, b = map(float, candidate_platt)
    require(math.isfinite(a) and math.isfinite(b) and b > 0.0, "invalid candidate positive-slope Platt map")
    pairs, p0, q0 = ref.exact_top3_pair_prior(horse_numbers, scores)
    z, missing = ref.transform_runner_values(runner_values, runner_moments)
    feature_pairs, raw20 = ref.race_pair_matrix(horse_numbers, z, missing)
    require(feature_pairs == pairs, "independent pair ordering mismatch")
    rider_raw = pair_jockey_sums(pairs, jockey_value_by_horse)
    x20 = ref.apply_pair_moments(raw20, frozen_20d_moments)
    if bool(jockey_moments["degenerate"]):
        rider_z = np.zeros(len(pairs), dtype=float)
    else:
        rider_z = (rider_raw - float(jockey_moments["mean"])) / float(jockey_moments["scale"])
    x21 = np.column_stack((x20, rider_z))
    eta = ref.logit(p0) + x21 @ coefficient
    candidate_raw = ref.sigmoid(eta)
    candidate_calibrated = ref.sigmoid(a + b * eta)
    selected = ref.choose_pair(pairs, eta)
    calibrated_selected = ref.choose_pair(pairs, a + b * eta)
    require(selected == calibrated_selected, "positive-slope candidate calibration changed selected pair")
    return {
        "pairs": pairs, "p0": p0, "q0": q0, "raw_basis_20": raw20,
        "standardized_basis_21": x21, "eta": eta,
        "candidate_raw_probability": candidate_raw,
        "candidate_calibrated_probability": candidate_calibrated,
        "selected_candidate": selected,
    }


def paired_hit_confidence_intervals(
    dates: Sequence[object],
    hit_by_method: Mapping[str, Sequence[float]],
    reference: str,
) -> dict[str, Any]:
    """Apply the exact saved schedule to methods and paired hit differences."""
    require(reference in hit_by_method, "frozen comparator missing from bootstrap methods")
    date_values = np.asarray(dates).astype(str)
    require(date_values.ndim == 1 and len(date_values) > 0, "empty paired bootstrap date vector")
    schedule = load_frozen_date_bootstrap_schedule(date_values)
    reference_hits = np.asarray(hit_by_method[reference], dtype=float)
    require(reference_hits.shape == date_values.shape and np.isfinite(reference_hits).all(),
            "invalid reference hit vector")
    all_races = np.ones(len(date_values), dtype=bool)
    output: dict[str, Any] = {"schedule": ref.date_bootstrap_schedule_receipt(schedule), "methods": {}}
    for name, values in hit_by_method.items():
        outcome = np.asarray(values, dtype=float)
        require(outcome.shape == date_values.shape and np.isfinite(outcome).all(), f"invalid hit vector: {name}")
        method = ref.bootstrap_masked_rate(date_values, outcome, all_races, schedule)
        if name != reference:
            difference = ref.bootstrap_masked_rate(date_values, outcome - reference_hits, all_races, schedule)
            method["paired_difference_from_reference"] = difference
        output["methods"][name] = method
    output["reference"] = reference
    return output


def load_frozen_date_bootstrap_schedule(dates: Sequence[object]):
    """Load and verify the existing int32 schedule; never generate a new one."""
    require(SCHEDULE_PATH.is_file() and not SCHEDULE_PATH.is_symlink(), "saved date bootstrap schedule missing or symlinked")
    require(SCHEDULE_RECEIPT_PATH.is_file() and not SCHEDULE_RECEIPT_PATH.is_symlink(),
            "saved date bootstrap receipt missing or symlinked")
    digest = hashlib.sha256(SCHEDULE_PATH.read_bytes()).hexdigest()
    require(digest == EXPECTED_SCHEDULE_SHA256, "saved date bootstrap schedule SHA changed")
    receipt = json.loads(SCHEDULE_RECEIPT_PATH.read_text(encoding="utf-8"))
    require(receipt.get("status") == "FROZEN_BEFORE_EVALUATION_METRICS", "saved schedule was not frozen before metrics")
    require(receipt.get("schedule_sha256") == EXPECTED_SCHEDULE_SHA256, "schedule receipt hash differs")
    date_values = np.asarray(dates).astype(str)
    unique_dates = tuple(sorted(set(date_values.tolist())))
    date_hash = hashlib.sha256("\n".join(unique_dates).encode("utf-8")).hexdigest()
    require(date_hash == receipt.get("date_inventory_sha256"), "evaluation dates differ from frozen schedule inventory")
    sampled = np.load(SCHEDULE_PATH, allow_pickle=False)
    require(sampled.dtype == np.int32 and sampled.shape == (2000, len(unique_dates)),
            "saved schedule dtype/shape changed")
    require(((sampled >= 0) & (sampled < len(unique_dates))).all(), "invalid sampled date index")
    multiplicities = np.zeros(sampled.shape, dtype=np.int32)
    np.add.at(multiplicities, (np.arange(sampled.shape[0])[:, None], sampled), 1)
    require((multiplicities.sum(axis=1) == len(unique_dates)).all(), "saved schedule draw has invalid date count")
    return ref.DateBootstrapSchedule(unique_dates, sampled, multiplicities, 20261011)

