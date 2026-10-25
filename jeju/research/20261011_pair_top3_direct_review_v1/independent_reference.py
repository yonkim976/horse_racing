"""Independent NumPy/math reproduction helpers for the direct-pair study.

This module intentionally does not import the study's core or fit/report code.
It contains no optimizer calls. Source data and evaluation labels may only be
loaded by the future driver after an explicit root fit-approval receipt passes
the guard; the synthetic self-test is outcome-free and does not touch files.
"""

from __future__ import annotations

from dataclasses import dataclass
import itertools
import hashlib
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np


RUNNER_COLUMNS = (
    "score",
    "hist_s1f_relpos_mean5",
    "hist_s1f_relpos_n",
    "hist_s1f_to_c4_forward_mean5",
    "hist_s1f_to_c4_pair_n",
    "hist_c4_to_g1f_forward_mean5",
    "hist_c4_to_g1f_pair_n",
)
MEAN_COLUMNS = (
    "hist_s1f_relpos_mean5",
    "hist_s1f_to_c4_forward_mean5",
    "hist_c4_to_g1f_forward_mean5",
)
COUNT_COLUMNS = (
    "hist_s1f_relpos_n",
    "hist_s1f_to_c4_pair_n",
    "hist_c4_to_g1f_pair_n",
)
BASIS_NAMES = tuple(
    name
    for column in RUNNER_COLUMNS
    for name in (f"sum:{column}", f"absdiff:{column}")
) + tuple(
    name
    for column in MEAN_COLUMNS
    for name in (f"missing_sum:{column}", f"missing_product:{column}")
)
PAIR_BINS = (0.0, 0.05, 0.10, 0.20, 0.30, 1.0)
BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SEED = 20261011


class ReproductionError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ReproductionError(message)


def canonical_pair(numbers: Sequence[int]) -> tuple[int, int]:
    require(len(numbers) == 2, f"expected a pair, got {numbers!r}")
    a, b = sorted(int(x) for x in numbers)
    require(a != b, f"duplicate horse in pair: {numbers!r}")
    return a, b


def sigmoid(values: Sequence[float] | np.ndarray) -> np.ndarray:
    """Numerically stable logistic transform, independent of model code."""
    x = np.asarray(values, dtype=float)
    require(np.isfinite(x).all(), "non-finite logit supplied to sigmoid")
    out = np.empty_like(x)
    positive = x >= 0.0
    out[positive] = 1.0 / (1.0 + np.exp(-x[positive]))
    exp_x = np.exp(x[~positive])
    out[~positive] = exp_x / (1.0 + exp_x)
    return out


def logit(probabilities: Sequence[float] | np.ndarray) -> np.ndarray:
    p = np.asarray(probabilities, dtype=float)
    require(np.isfinite(p).all() and ((p > 0.0) & (p < 1.0)).all(), "probability outside (0,1) for logit")
    return np.log(p) - np.log1p(-p)


def race_equal_runner_weights(race_ids: Sequence[object]) -> np.ndarray:
    ids = np.asarray(race_ids)
    require(ids.ndim == 1 and len(ids) > 0, "empty runner race-id vector")
    require(pd_is_not_null(ids), "null race id in runner weights")
    _, inverse, counts = np.unique(ids, return_inverse=True, return_counts=True)
    return 1.0 / (len(counts) * counts[inverse])


def pd_is_not_null(values: np.ndarray) -> bool:
    # Avoid importing pandas in this numerical-only module.
    for value in values.tolist():
        if value is None:
            return False
        if isinstance(value, (float, np.floating)) and math.isnan(float(value)):
            return False
    return True


@dataclass(frozen=True)
class RunnerMoments:
    columns: tuple[str, ...]
    mean: np.ndarray
    scale: np.ndarray
    degenerate: tuple[bool, ...]
    support_weight: tuple[float, ...]


@dataclass(frozen=True)
class PairMoments:
    mean: np.ndarray
    scale: np.ndarray
    degenerate: tuple[bool, ...]
    support_weight: tuple[float, ...]


def fit_runner_moments(h1_values: Mapping[str, Sequence[float]], race_ids: Sequence[object]) -> RunnerMoments:
    """Recompute H1 runner moments without importing the candidate implementation."""
    require(len(race_ids) > 0, "empty H1 runner cohort")
    weights = race_equal_runner_weights(race_ids)
    means = np.empty(7, dtype=float)
    scales = np.empty(7, dtype=float)
    degenerate: list[bool] = []
    support: list[float] = []
    for j, name in enumerate(RUNNER_COLUMNS):
        values = np.asarray(h1_values[name], dtype=float)
        require(values.ndim == 1 and len(values) == len(weights), f"H1 runner length mismatch: {name}")
        valid = np.isfinite(values)
        if name not in MEAN_COLUMNS:
            require(valid.all(), f"non-finite H1 runner column: {name}")
        total = float(weights[valid].sum())
        require(total > 0.0, f"no H1 support for {name}")
        center = float(np.dot(weights[valid], values[valid]) / total)
        variance = float(np.dot(weights[valid], (values[valid] - center) ** 2) / total)
        require(math.isfinite(center) and math.isfinite(variance) and variance >= 0.0, f"invalid H1 moments for {name}")
        sd = math.sqrt(variance)
        is_degenerate = sd <= 1e-12
        means[j] = center
        scales[j] = 1.0 if is_degenerate else sd
        degenerate.append(is_degenerate)
        support.append(total)
    return RunnerMoments(RUNNER_COLUMNS, means, scales, tuple(degenerate), tuple(support))


def transform_runner_values(values: Mapping[str, Sequence[float]], moments: RunnerMoments) -> tuple[np.ndarray, np.ndarray]:
    require(moments.columns == RUNNER_COLUMNS, "runner moment columns differ from frozen order")
    n = len(values[RUNNER_COLUMNS[0]])
    z = np.empty((n, 7), dtype=float)
    missing = np.zeros((n, 3), dtype=float)
    for j, name in enumerate(RUNNER_COLUMNS):
        x = np.asarray(values[name], dtype=float)
        require(x.ndim == 1 and len(x) == n, f"runner transform length mismatch: {name}")
        valid = np.isfinite(x)
        if name in MEAN_COLUMNS:
            missing[:, MEAN_COLUMNS.index(name)] = (~valid).astype(float)
            z[:, j] = 0.0
            z[valid, j] = (x[valid] - moments.mean[j]) / moments.scale[j]
        else:
            require(valid.all(), f"non-finite runner input during transform: {name}")
            z[:, j] = (x - moments.mean[j]) / moments.scale[j]
        if moments.degenerate[j]:
            z[:, j] = 0.0
    require(np.isfinite(z).all(), "non-finite transformed runner matrix")
    return z, missing


def symmetric_basis(zi: Sequence[float], zj: Sequence[float], mi: Sequence[float], mj: Sequence[float]) -> np.ndarray:
    a = np.asarray(zi, dtype=float)
    b = np.asarray(zj, dtype=float)
    ma = np.asarray(mi, dtype=float)
    mb = np.asarray(mj, dtype=float)
    require(a.shape == b.shape == (7,) and ma.shape == mb.shape == (3,), "invalid runner vector shape")
    out = [v for pair in zip(a, b, strict=True) for v in (float(pair[0] + pair[1]), float(abs(pair[0] - pair[1])))]
    out.extend(v for pair in zip(ma, mb, strict=True) for v in (float(pair[0] + pair[1]), float(pair[0] * pair[1])))
    result = np.asarray(out, dtype=float)
    require(result.shape == (20,) and np.isfinite(result).all(), "invalid pair-symmetric basis")
    return result


def race_pair_matrix(horse_numbers: Sequence[int], z: np.ndarray, missing: np.ndarray) -> tuple[list[tuple[int, int]], np.ndarray]:
    numbers = np.asarray(horse_numbers, dtype=int)
    z = np.asarray(z, dtype=float)
    missing = np.asarray(missing, dtype=float)
    require(len(numbers) >= 4 and len(set(numbers.tolist())) == len(numbers), "invalid race roster for pair basis")
    require(z.shape == (len(numbers), 7) and missing.shape == (len(numbers), 3), "race runner basis shape mismatch")
    order = np.argsort(numbers, kind="stable")
    numbers = numbers[order]
    z = z[order]
    missing = missing[order]
    pairs = list(itertools.combinations(numbers.tolist(), 2))
    pos = {int(number): index for index, number in enumerate(numbers)}
    matrix = np.vstack([symmetric_basis(z[pos[a]], z[pos[b]], missing[pos[a]], missing[pos[b]]) for a, b in pairs])
    return pairs, matrix


def fit_pair_moments(h1_race_bases: Sequence[np.ndarray]) -> PairMoments:
    arrays = [np.asarray(a, dtype=float) for a in h1_race_bases]
    require(len(arrays) > 0 and all(a.ndim == 2 and a.shape[1] == 20 and len(a) > 0 for a in arrays), "invalid H1 pair bases")
    require(all(np.isfinite(a).all() for a in arrays), "non-finite H1 pair basis")
    centers = np.vstack([a.mean(axis=0) for a in arrays]).mean(axis=0)
    variance = np.vstack([((a - centers) ** 2).mean(axis=0) for a in arrays]).mean(axis=0)
    scales = np.sqrt(np.maximum(variance, 0.0))
    dead = scales <= 1e-12
    scales[dead] = 1.0
    centers[dead] = 0.0
    return PairMoments(centers, scales, tuple(bool(x) for x in dead), tuple(float(len(arrays)) for _ in range(20)))


def apply_pair_moments(basis: np.ndarray, moments: PairMoments) -> np.ndarray:
    x = np.asarray(basis, dtype=float)
    require(x.ndim == 2 and x.shape[1] == 20 and np.isfinite(x).all(), "invalid pair basis matrix")
    out = (x - moments.mean) / moments.scale
    for j, dead in enumerate(moments.degenerate):
        if dead:
            out[:, j] = 0.0
    require(np.isfinite(out).all(), "non-finite standardized pair matrix")
    return out


def exact_top3_pair_prior(horse_numbers: Sequence[int], scores: Sequence[float]) -> tuple[list[tuple[int, int]], np.ndarray, dict[tuple[int, int, int], float]]:
    """Canonical tau=1 additive triple distribution and all pair marginals."""
    rows = sorted(((int(n), float(s)) for n, s in zip(horse_numbers, scores, strict=True)), key=lambda x: x[0])
    numbers = [n for n, _ in rows]
    score = {n: s for n, s in rows}
    require(len(numbers) >= 4 and len(set(numbers)) == len(numbers), "invalid prior roster")
    require(np.isfinite(np.asarray(list(score.values()), dtype=float)).all(), "non-finite prior score")
    triples = list(itertools.combinations(numbers, 3))
    energies = [math.fsum(score[n] for n in triple) for triple in triples]
    peak = max(energies)
    weights = [math.exp(e - peak) for e in energies]
    denom = math.fsum(weights)
    require(math.isfinite(denom) and denom > 0.0, "invalid prior normalizer")
    q = {triple: weight / denom for triple, weight in zip(triples, weights, strict=True)}
    pair_terms: dict[tuple[int, int], list[float]] = {pair: [] for pair in itertools.combinations(numbers, 2)}
    for triple in triples:
        for pair in itertools.combinations(triple, 2):
            pair_terms[pair].append(q[triple])
    pairs = list(pair_terms)
    p0 = np.asarray([math.fsum(pair_terms[pair]) for pair in pairs], dtype=float)
    require(np.isfinite(p0).all() and ((p0 > 0.0) & (p0 < 1.0)).all(), "invalid prior pair marginal")
    require(abs(math.fsum(q.values()) - 1.0) <= 1e-12, "triple prior mass differs from one")
    require(abs(math.fsum(p0.tolist()) - 3.0) <= 1e-12, "pair prior mass differs from three")
    return pairs, p0, q


def choose_pair(pairs: Sequence[tuple[int, int]], scores: Sequence[float]) -> tuple[int, int]:
    values = np.asarray(scores, dtype=float)
    require(len(pairs) == len(values) and len(values) > 0 and np.isfinite(values).all(), "invalid pair selector inputs")
    canonical = [tuple(sorted((int(a), int(b)))) for a, b in pairs]
    maximum = float(values.max())
    return min(pair for pair, value in zip(canonical, values, strict=True) if float(value) == maximum)


def pair_label(finish_by_horse: Mapping[int, int], pairs: Sequence[tuple[int, int]]) -> np.ndarray:
    return np.asarray([float(finish_by_horse[a] <= 3 and finish_by_horse[b] <= 3) for a, b in pairs], dtype=float)


def produce_race_predictions(
    horse_numbers: Sequence[int],
    scores: Sequence[float],
    runner_values: Mapping[str, Sequence[float]],
    runner_moments: RunnerMoments,
    pair_moments: PairMoments,
    beta: Sequence[float],
    candidate_platt: Sequence[float],
    baseline_platt: Sequence[float],
) -> dict[str, Any]:
    """Apply already stored H1/H2 parameters; this function never fits anything."""
    coefficient = np.asarray(beta, dtype=float)
    c_a, c_b = map(float, candidate_platt)
    b_a, b_b = map(float, baseline_platt)
    require(coefficient.shape == (20,) and np.isfinite(coefficient).all(), "invalid stored beta")
    require(math.isfinite(c_a) and math.isfinite(c_b) and c_b > 0.0, "invalid candidate Platt parameters")
    require(math.isfinite(b_a) and math.isfinite(b_b) and b_b > 0.0, "invalid baseline Platt parameters")
    pairs0, p0, q = exact_top3_pair_prior(horse_numbers, scores)
    z, missing = transform_runner_values(runner_values, runner_moments)
    pairs, raw_basis = race_pair_matrix(horse_numbers, z, missing)
    require(pairs == pairs0, "pair ordering differs between prior and feature basis")
    design = apply_pair_moments(raw_basis, pair_moments)
    raw_offset = logit(p0)
    eta = raw_offset + design @ coefficient
    p_raw = sigmoid(eta)
    p_candidate_cal = sigmoid(c_a + c_b * eta)
    p_baseline_cal = sigmoid(b_a + b_b * raw_offset)
    candidate_pick = choose_pair(pairs, eta)
    candidate_cal_pick = choose_pair(pairs, p_candidate_cal)
    baseline_pick = choose_pair(pairs, raw_offset)
    require(candidate_pick == candidate_cal_pick, "positive-slope candidate Platt changed selected pair numerically")
    return {
        "pairs": pairs,
        "p0": p0,
        "q0": q,
        "basis": raw_basis,
        "standardized_basis": design,
        "eta": eta,
        "candidate_raw_probability": p_raw,
        "candidate_calibrated_probability": p_candidate_cal,
        "baseline_calibrated_probability": p_baseline_cal,
        "candidate_pair": candidate_pick,
        "baseline_pair": baseline_pick,
    }


def bce_from_logits(logits: Sequence[float], labels: Sequence[float]) -> np.ndarray:
    z = np.asarray(logits, dtype=float)
    y = np.asarray(labels, dtype=float)
    require(z.shape == y.shape and np.isfinite(z).all() and np.isfinite(y).all(), "invalid BCE inputs")
    require(((y == 0.0) | (y == 1.0)).all(), "non-binary labels")
    return np.logaddexp(0.0, z) - y * z


def h1_objective_gradient(
    beta: Sequence[float],
    standardized_basis_by_race: Sequence[np.ndarray],
    p0_by_race: Sequence[np.ndarray],
    labels_by_race: Sequence[np.ndarray],
) -> tuple[float, np.ndarray]:
    """Recompute race-equal H1 BCE + unit ridge at stored beta; no optimizer."""
    coefficient = np.asarray(beta, dtype=float)
    require(coefficient.shape == (20,) and np.isfinite(coefficient).all(), "invalid stored H1 beta")
    require(len(standardized_basis_by_race) == len(p0_by_race) == len(labels_by_race) > 0,
            "H1 race input counts differ")
    n_races = len(standardized_basis_by_race)
    objective_parts: list[float] = []
    gradient = coefficient.copy()
    for index, (basis, prior, labels) in enumerate(zip(
        standardized_basis_by_race, p0_by_race, labels_by_race, strict=True
    )):
        x = np.asarray(basis, dtype=float)
        p = np.asarray(prior, dtype=float)
        y = np.asarray(labels, dtype=float)
        require(x.ndim == 2 and x.shape[1] == 20 and len(x) > 0, f"invalid H1 basis race {index}")
        require(x.shape[0] == len(p) == len(y), f"H1 pair lengths differ in race {index}")
        require(np.isfinite(x).all() and np.isfinite(p).all() and np.isfinite(y).all(), f"non-finite H1 race {index}")
        require(((p > 0.0) & (p < 1.0)).all(), f"H1 p0 outside (0,1) in race {index}")
        logits = logit(p) + x @ coefficient
        require(np.isfinite(logits).all(), f"non-finite H1 logits in race {index}")
        residual = sigmoid(logits) - y
        objective_parts.append(float(np.mean(bce_from_logits(logits, y))))
        gradient += (x.T @ residual) / (n_races * len(x))
    objective = float(np.mean(objective_parts) + 0.5 * np.dot(coefficient, coefficient))
    require(math.isfinite(objective) and np.isfinite(gradient).all(), "non-finite independent H1 objective/gradient")
    return objective, gradient


def platt_objective_gradient(
    parameters: Sequence[float],
    raw_logits_by_race: Sequence[np.ndarray],
    labels_by_race: Sequence[np.ndarray],
) -> tuple[float, np.ndarray]:
    """Recompute race-equal H2 positive-slope Platt BCE at saved A/B."""
    theta = np.asarray(parameters, dtype=float)
    require(theta.shape == (2,) and np.isfinite(theta).all(), "invalid stored Platt A/B")
    require(theta[1] > 0.0, "Platt slope must be positive")
    require(len(raw_logits_by_race) == len(labels_by_race) > 0, "H2 race input counts differ")
    n_races = len(raw_logits_by_race)
    objective_parts: list[float] = []
    gradient = np.zeros(2, dtype=float)
    for index, (raw, labels) in enumerate(zip(raw_logits_by_race, labels_by_race, strict=True)):
        u = np.asarray(raw, dtype=float)
        y = np.asarray(labels, dtype=float)
        require(u.ndim == 1 and len(u) > 0 and u.shape == y.shape, f"invalid H2 pair input in race {index}")
        require(np.isfinite(u).all() and np.isfinite(y).all(), f"non-finite H2 race {index}")
        logits = theta[0] + theta[1] * u
        p = sigmoid(logits)
        residual = p - y
        objective_parts.append(float(np.mean(bce_from_logits(logits, y))))
        gradient[0] += float(np.mean(residual)) / n_races
        gradient[1] += float(np.mean(residual * u)) / n_races
    objective = float(np.mean(objective_parts))
    require(math.isfinite(objective) and np.isfinite(gradient).all(), "non-finite independent H2 objective/gradient")
    return objective, gradient


def projected_box_gradient(
    parameters: Sequence[float],
    gradient: Sequence[float],
    bounds: Sequence[tuple[float, float]] = ((-20.0, 20.0), (0.05, 20.0)),
) -> np.ndarray:
    """Independent KKT projected gradient for minimization within box bounds."""
    theta = np.asarray(parameters, dtype=float)
    grad = np.asarray(gradient, dtype=float)
    require(theta.ndim == grad.ndim == 1 and len(theta) == len(grad) == len(bounds), "projected gradient shape mismatch")
    result = grad.copy()
    for index, (lower, upper) in enumerate(bounds):
        require(math.isfinite(float(theta[index])) and lower <= theta[index] <= upper, "parameter outside Platt bounds")
        if theta[index] == lower and grad[index] >= 0.0:
            result[index] = 0.0
        elif theta[index] == upper and grad[index] <= 0.0:
            result[index] = 0.0
    return result


def race_equal_pair_metrics(probabilities: Sequence[np.ndarray], logits: Sequence[np.ndarray], labels: Sequence[np.ndarray]) -> dict[str, float]:
    require(len(probabilities) == len(logits) == len(labels) > 0, "metric race lists differ")
    race_brier=[]; race_logloss=[]
    for p, z, y in zip(probabilities, logits, labels, strict=True):
        pp=np.asarray(p,dtype=float); zz=np.asarray(z,dtype=float); yy=np.asarray(y,dtype=float)
        require(pp.shape==zz.shape==yy.shape and len(pp)>0, "metric pair arrays differ")
        require(np.isfinite(pp).all() and ((pp>=0)&(pp<=1)).all(), "invalid probability in metrics")
        race_brier.append(float(np.mean((pp-yy)**2)))
        race_logloss.append(float(np.mean(bce_from_logits(zz,yy))))
    return {"brier":float(np.mean(race_brier)),"log_loss":float(np.mean(race_logloss)),"races":len(race_brier)}


def reliability_bins(probability: Sequence[np.ndarray], labels: Sequence[np.ndarray], *, selected: bool) -> list[dict[str, Any]]:
    require(len(probability)==len(labels)>0,"reliability race lists differ")
    flat_p=[]; flat_y=[]; flat_w=[]; flat_r=[]
    for race_index,(pp,yy) in enumerate(zip(probability,labels,strict=True)):
        p=np.asarray(pp,dtype=float); y=np.asarray(yy,dtype=float)
        require(p.shape==y.shape and len(p)>0,"reliability pair arrays differ")
        weight=np.ones(len(p),dtype=float) if selected else np.full(len(p),1.0/len(p),dtype=float)
        flat_p.extend(p.tolist());flat_y.extend(y.tolist());flat_w.extend(weight.tolist());flat_r.extend([race_index]*len(p))
    p=np.asarray(flat_p); y=np.asarray(flat_y); w=np.asarray(flat_w); r=np.asarray(flat_r)
    bins=[]
    for j,(lo,hi) in enumerate(zip(PAIR_BINS[:-1],PAIR_BINS[1:],strict=True)):
        mask=(p>=lo)&((p<hi) if j<len(PAIR_BINS)-2 else (p<=hi))
        weight_sum=float(w[mask].sum())
        bins.append({"lower":lo,"upper":hi,"pairs":int(mask.sum()),"races":int(len(np.unique(r[mask]))),
                     "mean_prediction":float(np.dot(w[mask],p[mask])/weight_sum) if weight_sum else None,
                     "observed_rate":float(np.dot(w[mask],y[mask])/weight_sum) if weight_sum else None,
                     "weight_sum":weight_sum})
    return bins


def date_bootstrap_differences(
    dates: Sequence[object],
    hit_arrays: Mapping[str, Sequence[float]],
    *,
    n_resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, dict[str, float | int]]:
    """Paired race-weighted date-cluster bootstrap with one shared schedule.

    Each input is a per-race outcome (for example, a selected-pair hit flag).
    Date clusters are sampled with replacement; all races on a sampled date
    travel together. Each method uses the same resample schedule.
    """
    result = paired_date_bootstrap(
        dates,
        hit_arrays,
        n_resamples=n_resamples,
        seed=seed,
    )
    return {
        name: {
            "lower_95": entry["lower_95"],
            "upper_95": entry["upper_95"],
            "resamples": entry["resamples"],
            "dates": entry["dates"],
            "seed": entry["seed"],
        }
        for name, entry in result.items()
    }


def paired_date_bootstrap(
    dates: Sequence[object],
    values_by_method: Mapping[str, Sequence[float]],
    *,
    valid_by_method: Mapping[str, Sequence[bool]] | None = None,
    reference: str | None = None,
    n_resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, dict[str, Any]]:
    """Calculate paired date-cluster CIs for race-level values.

    Optional validity masks support fixed prediction subsets such as selected
    pairs with calibrated probability >= .20. Resamples with an empty subset
    are counted as undefined. If `reference` is given, paired method-minus-
    reference differences use the same sampled date multiplicities.
    """
    date_values = np.asarray(dates).astype(str)
    require(date_values.ndim == 1 and len(date_values) > 0 and n_resamples > 0, "empty bootstrap input")
    require(bool(values_by_method), "no bootstrap methods supplied")
    unique_dates = np.asarray(sorted(set(date_values.tolist())), dtype=str)
    date_to_index = {value: index for index, value in enumerate(unique_dates.tolist())}
    date_index = np.asarray([date_to_index[value] for value in date_values], dtype=int)
    if valid_by_method is None:
        valid_by_method = {}
    require(reference is None or reference in values_by_method, "bootstrap reference is missing")
    schedule = np.random.default_rng(seed).integers(
        0, len(unique_dates), size=(n_resamples, len(unique_dates))
    )
    date_multiplicity = np.zeros((n_resamples, len(unique_dates)), dtype=float)
    rows = np.arange(n_resamples)[:, None]
    np.add.at(date_multiplicity, (rows, schedule), 1.0)

    prepared: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for name, values in values_by_method.items():
        outcome = np.asarray(values, dtype=float)
        require(outcome.shape == date_values.shape and np.isfinite(outcome).all(), f"invalid bootstrap values: {name}")
        if name in valid_by_method:
            valid = np.asarray(valid_by_method[name], dtype=bool)
            require(valid.shape == date_values.shape, f"invalid bootstrap validity mask: {name}")
        else:
            valid = np.ones(len(date_values), dtype=bool)
        sums = np.bincount(date_index, weights=np.where(valid, outcome, 0.0), minlength=len(unique_dates))
        counts = np.bincount(date_index, weights=valid.astype(float), minlength=len(unique_dates))
        prepared[name] = sums, counts

    def draw_values(name: str) -> tuple[np.ndarray, np.ndarray]:
        sums, counts = prepared[name]
        numerators = date_multiplicity @ sums
        denominators = date_multiplicity @ counts
        draws = np.full(n_resamples, np.nan, dtype=float)
        okay = denominators > 0.0
        draws[okay] = numerators[okay] / denominators[okay]
        return draws, okay

    output: dict[str, dict[str, Any]] = {}
    names_in_order = list(values_by_method)
    if reference is not None:
        names_in_order.remove(reference)
        names_in_order.insert(0, reference)
    for name in names_in_order:
        draws, okay = draw_values(name)
        entry: dict[str, Any] = {
            "estimate": float(np.mean(np.asarray(values_by_method[name], dtype=float)[
                np.asarray(valid_by_method.get(name, np.ones(len(date_values), dtype=bool)), dtype=bool)
            ])) if prepared[name][1].sum() > 0.0 else None,
            "lower_95": float(np.quantile(draws[okay], 0.025)) if okay.any() else None,
            "upper_95": float(np.quantile(draws[okay], 0.975)) if okay.any() else None,
            "resamples": int(n_resamples),
            "valid_resamples": int(okay.sum()),
            "undefined_resamples": int((~okay).sum()),
            "dates": int(len(unique_dates)),
            "seed": int(seed),
        }
        if reference is not None and name != reference:
            left, left_ok = draw_values(name)
            right, right_ok = draw_values(reference)
            paired_ok = left_ok & right_ok
            differences = left[paired_ok] - right[paired_ok]
            reference_valid = np.asarray(valid_by_method.get(reference, np.ones(len(date_values), dtype=bool)), dtype=bool)
            method_valid = np.asarray(valid_by_method.get(name, np.ones(len(date_values), dtype=bool)), dtype=bool)
            if np.array_equal(method_valid, reference_valid):
                point_difference = entry["estimate"] - output[reference]["estimate"]
                entry["difference"] = {
                    "estimate": float(point_difference),
                    "lower_95": float(np.quantile(differences, 0.025)) if len(differences) else None,
                    "upper_95": float(np.quantile(differences, 0.975)) if len(differences) else None,
                    "valid_resamples": int(len(differences)),
                    "undefined_resamples": int(n_resamples - len(differences)),
                }
            else:
                # A paired rate difference requires the same fixed race subset.
                # Report its uncertainty as undefined instead of pairing unlike
                # denominators or choosing a post-result mask.
                entry["difference"] = {
                    "estimate": None,
                    "lower_95": None,
                    "upper_95": None,
                    "valid_resamples": 0,
                    "undefined_resamples": int(n_resamples),
                    "reason": "method and reference validity masks differ",
                }
        output[name] = entry
    return output


@dataclass(frozen=True)
class DateBootstrapSchedule:
    dates: tuple[str, ...]
    sampled_date_indices: np.ndarray
    multiplicities: np.ndarray
    seed: int


def make_date_bootstrap_schedule(
    dates: Sequence[object],
    *,
    n_resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> DateBootstrapSchedule:
    """Create one global ISO-date schedule shared by policies and subgroups."""
    values = np.asarray(dates).astype(str)
    require(values.ndim == 1 and len(values) > 0 and n_resamples > 0, "empty global bootstrap date set")
    unique = tuple(sorted(set(values.tolist())))
    rng = np.random.default_rng(seed)
    sampled = rng.integers(0, len(unique), size=(n_resamples, len(unique)), dtype=np.int64)
    multiplicities = np.zeros((n_resamples, len(unique)), dtype=np.int32)
    np.add.at(multiplicities, (np.arange(n_resamples)[:, None], sampled), 1)
    require((multiplicities.sum(axis=1) == len(unique)).all(), "bootstrap draw does not contain fixed date count")
    return DateBootstrapSchedule(unique, sampled, multiplicities, int(seed))


def date_bootstrap_schedule_receipt(schedule: DateBootstrapSchedule) -> dict[str, Any]:
    """Return a portable hash receipt for the exact resampling schedule."""
    # Little-endian int64 bytes make the hash independent of host byte order.
    sampled = np.asarray(schedule.sampled_date_indices, dtype="<i8", order="C")
    date_payload = "\n".join(schedule.dates).encode("utf-8")
    return {
        "dates": len(schedule.dates),
        "resamples": int(sampled.shape[0]),
        "seed": int(schedule.seed),
        "date_list_sha256": hashlib.sha256(date_payload).hexdigest(),
        "sampled_date_indices_sha256_le_i64": hashlib.sha256(sampled.tobytes(order="C")).hexdigest(),
    }


def bootstrap_masked_rate(
    dates: Sequence[object],
    values: Sequence[float],
    include: Sequence[bool],
    schedule: DateBootstrapSchedule,
) -> dict[str, Any]:
    """Bootstrap a race-level rate under the shared date multiplicity matrix."""
    date_values = np.asarray(dates).astype(str)
    outcome = np.asarray(values, dtype=float)
    mask = np.asarray(include, dtype=bool)
    require(date_values.shape == outcome.shape == mask.shape and len(date_values) > 0, "invalid masked bootstrap arrays")
    require(np.isfinite(outcome).all(), "non-finite masked bootstrap outcome")
    index_by_date = {day: i for i, day in enumerate(schedule.dates)}
    require(set(date_values.tolist()).issubset(index_by_date), "bootstrap input date absent from frozen schedule")
    date_index = np.asarray([index_by_date[day] for day in date_values], dtype=int)
    race_weights = schedule.multiplicities[:, date_index].astype(float, copy=False)
    inclusion = mask.astype(float)
    denominator = race_weights @ inclusion
    numerator = race_weights @ (inclusion * outcome)
    valid = denominator > 0.0
    draws = np.full(len(denominator), np.nan, dtype=float)
    draws[valid] = numerator[valid] / denominator[valid]
    estimate = float(outcome[mask].mean()) if mask.any() else None
    return {
        "estimate": estimate,
        "lower_95": float(np.quantile(draws[valid], 0.025)) if valid.any() else None,
        "upper_95": float(np.quantile(draws[valid], 0.975)) if valid.any() else None,
        "resamples": int(len(draws)),
        "valid_resamples": int(valid.sum()),
        "undefined_resamples": int((~valid).sum()),
        "dates_in_global_schedule": int(len(schedule.dates)),
        "seed": int(schedule.seed),
    }


def evaluate_prediction_records(
    pair_rows: Sequence[Mapping[str, Any]],
    comparator_pairs: Mapping[str, Mapping[str, tuple[int, int]]],
    candidate_platt_by_year: Mapping[int, Sequence[float]],
    baseline_platt_by_year: Mapping[int, Sequence[float]],
    schedule: DateBootstrapSchedule,
) -> dict[str, Any]:
    """Recompute prescribed outcome/calibration summaries from normalized rows.

    Required per-pair fields are `race_id`, `race_date`, `evaluation_year`,
    `distance_m`, `horse_a`, `horse_b`, `p0`, `eta`, `candidate_calibrated_probability`,
    `baseline_calibrated_probability`, `y_pair`, and `candidate_selected`.
    Comparator pair maps are independently reconstructed from frozen source
    tables before this function is called.
    """
    require(len(pair_rows) > 0, "empty evaluation pair table")
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for row in pair_rows:
        race_id = str(row["race_id"])
        grouped.setdefault(race_id, []).append(row)
    race_ids = sorted(grouped)
    dates: list[str] = []
    years: list[int] = []
    distances: list[int] = []
    race_labels: list[np.ndarray] = []
    candidate_all_p: list[np.ndarray] = []
    candidate_all_z: list[np.ndarray] = []
    baseline_all_p: list[np.ndarray] = []
    baseline_all_z: list[np.ndarray] = []
    candidate_selected_p: list[np.ndarray] = []
    candidate_selected_z: list[np.ndarray] = []
    baseline_selected_p: list[np.ndarray] = []
    baseline_selected_z: list[np.ndarray] = []
    candidate_selected_y: list[np.ndarray] = []
    baseline_selected_y: list[np.ndarray] = []
    selected_hits: dict[str, list[float]] = {"direct_candidate": []}
    candidate_pair_by_race: dict[str, tuple[int, int]] = {}
    baseline_pair_by_race: dict[str, tuple[int, int]] = {}
    candidate_sum_residual: list[float] = []
    baseline_sum_residual: list[float] = []
    threshold_mask: list[bool] = []
    threshold_hits: list[float] = []

    for race_id in race_ids:
        rows = sorted(grouped[race_id], key=lambda row: canonical_pair((int(row["horse_a"]), int(row["horse_b"]))))
        first = rows[0]
        date = str(first["race_date"])
        year = int(first["evaluation_year"])
        distance = int(first["distance_m"])
        require(all(str(row["race_date"]) == date and int(row["evaluation_year"]) == year
                    and int(row["distance_m"]) == distance for row in rows),
                f"race metadata changes within {race_id}")
        require(year in candidate_platt_by_year and year in baseline_platt_by_year,
                f"missing H2 calibration for evaluation year {year}")
        pairs = [canonical_pair((int(row["horse_a"]), int(row["horse_b"]))) for row in rows]
        require(pairs == sorted(pairs) and len(set(pairs)) == len(pairs), f"pair keys not canonical/unique in {race_id}")
        roster = sorted({number for pair in pairs for number in pair})
        require(len(pairs) == math.comb(len(roster), 2), f"incomplete pair enumeration in {race_id}")
        require(set(pairs) == set(itertools.combinations(roster, 2)), f"pair roster gap in {race_id}")
        y = np.asarray([float(row["y_pair"]) for row in rows], dtype=float)
        p0 = np.asarray([float(row["p0"]) for row in rows], dtype=float)
        eta = np.asarray([float(row["eta"]) for row in rows], dtype=float)
        stored_candidate_p = np.asarray([float(row["candidate_calibrated_probability"]) for row in rows], dtype=float)
        stored_baseline_p = np.asarray([float(row["baseline_calibrated_probability"]) for row in rows], dtype=float)
        selected_flags = np.asarray([bool(row["candidate_selected"]) for row in rows], dtype=bool)
        require(y.shape == p0.shape == eta.shape == stored_candidate_p.shape == stored_baseline_p.shape,
                f"pair vector length mismatch in {race_id}")
        require(np.isfinite(y).all() and np.isfinite(p0).all() and np.isfinite(eta).all()
                and np.isfinite(stored_candidate_p).all() and np.isfinite(stored_baseline_p).all(),
                f"non-finite evaluation pair value in {race_id}")
        require(int(y.sum()) == 3 and ((y == 0.0) | (y == 1.0)).all(), f"invalid pair labels in {race_id}")
        require(((p0 > 0.0) & (p0 < 1.0)).all(), f"invalid p0 in {race_id}")
        require(((stored_candidate_p >= 0.0) & (stored_candidate_p <= 1.0)).all()
                and ((stored_baseline_p >= 0.0) & (stored_baseline_p <= 1.0)).all(),
                f"invalid calibrated probabilities in {race_id}")
        require(int(selected_flags.sum()) == 1, f"candidate selected flag count is not one in {race_id}")

        c_a, c_b = map(float, candidate_platt_by_year[year])
        b_a, b_b = map(float, baseline_platt_by_year[year])
        require(c_b > 0.0 and b_b > 0.0, f"non-positive Platt slope in {year}")
        candidate_z = c_a + c_b * eta
        baseline_offset = logit(p0)
        baseline_z = b_a + b_b * baseline_offset
        candidate_p = sigmoid(candidate_z)
        baseline_p = sigmoid(baseline_z)
        assert_close(stored_candidate_p, candidate_p, label=f"candidate calibrated p {race_id}")
        assert_close(stored_baseline_p, baseline_p, label=f"baseline calibrated p {race_id}")

        candidate_pair = choose_pair(pairs, eta)
        candidate_prob_pair = choose_pair(pairs, stored_candidate_p)
        require(candidate_pair == candidate_prob_pair, f"candidate Platt changed selected pair in {race_id}")
        selected_pair_by_flag = pairs[int(np.flatnonzero(selected_flags)[0])]
        require(candidate_pair == selected_pair_by_flag, f"saved candidate selector differs in {race_id}")
        baseline_pair = choose_pair(pairs, baseline_offset)
        baseline_index = pairs.index(baseline_pair)
        candidate_index = pairs.index(candidate_pair)
        candidate_hit = float(y[candidate_index])
        baseline_hit = float(y[baseline_index])

        dates.append(date); years.append(year); distances.append(distance); race_labels.append(y)
        candidate_all_p.append(candidate_p); candidate_all_z.append(candidate_z)
        baseline_all_p.append(baseline_p); baseline_all_z.append(baseline_z)
        candidate_selected_p.append(np.asarray([candidate_p[candidate_index]]))
        candidate_selected_z.append(np.asarray([candidate_z[candidate_index]]))
        candidate_selected_y.append(np.asarray([candidate_hit]))
        baseline_selected_p.append(np.asarray([baseline_p[baseline_index]]))
        baseline_selected_z.append(np.asarray([baseline_z[baseline_index]]))
        baseline_selected_y.append(np.asarray([baseline_hit]))
        candidate_pair_by_race[race_id] = candidate_pair
        baseline_pair_by_race[race_id] = baseline_pair
        candidate_sum_residual.append(float(math.fsum(candidate_p.tolist()) - 3.0))
        baseline_sum_residual.append(float(math.fsum(baseline_p.tolist()) - 3.0))
        selected_hits["direct_candidate"].append(candidate_hit)
        threshold_mask.append(float(candidate_p[candidate_index]) >= 0.20)
        threshold_hits.append(candidate_hit)
        for name, mapping in comparator_pairs.items():
            require(name != "direct_candidate", "comparator name collides with direct candidate")
            require(race_id in mapping, f"comparator {name} missing {race_id}")
            pair = canonical_pair(mapping[race_id])
            require(pair in pairs, f"comparator {name} pair absent from roster: {race_id}/{pair}")
            hit = float(y[pairs.index(pair)])
            selected_hits.setdefault(name, []).append(hit)

    require(set(comparator_pairs), "no comparator pair sources supplied")
    unique_dates = sorted(set(dates))
    require(tuple(unique_dates) == schedule.dates, "global bootstrap date set differs from evaluation races")
    require(len(unique_dates) == 269, f"expected frozen 269 evaluation dates, found {len(unique_dates)}")
    hit_rates: dict[str, dict[str, Any]] = {}
    bootstrap: dict[str, Any] = {}
    for name, values in selected_hits.items():
        vector = np.asarray(values, dtype=float)
        require(vector.shape == (len(race_ids),) and np.isin(vector, (0.0, 1.0)).all(), f"invalid hit vector for {name}")
        point = float(vector.mean())
        hit_rates[name] = {"races": len(race_ids), "hits": int(vector.sum()), "hit_rate": point}
        bootstrap[name] = bootstrap_masked_rate(dates, vector, np.ones(len(race_ids), dtype=bool), schedule)
        if name != "direct_candidate":
            delta = np.asarray(selected_hits["direct_candidate"], dtype=float) - vector
            bootstrap[f"direct_candidate_minus_{name}"] = bootstrap_masked_rate(
                dates, delta, np.ones(len(race_ids), dtype=bool), schedule
            )

    selected_metric = {
        "candidate": race_equal_pair_metrics(candidate_selected_p, candidate_selected_z, candidate_selected_y),
        "baseline": race_equal_pair_metrics(baseline_selected_p, baseline_selected_z, baseline_selected_y),
    }
    all_pair_metric = {
        "candidate": race_equal_pair_metrics(candidate_all_p, candidate_all_z, race_labels),
        "baseline": race_equal_pair_metrics(baseline_all_p, baseline_all_z, race_labels),
    }
    selected_reliability = {
        "candidate": reliability_bins(candidate_selected_p, candidate_selected_y, selected=True),
        "baseline": reliability_bins(baseline_selected_p, baseline_selected_y, selected=True),
    }
    all_pair_reliability = {
        "candidate": reliability_bins(candidate_all_p, race_labels, selected=False),
        "baseline": reliability_bins(baseline_all_p, race_labels, selected=False),
    }
    threshold = np.asarray(threshold_mask, dtype=bool)
    threshold_hits_array = np.asarray(threshold_hits, dtype=float)
    threshold_report = {
        "eligible_races": int(threshold.sum()),
        "coverage": float(threshold.mean()),
        "hits": int(threshold_hits_array[threshold].sum()),
        "hit_rate": float(threshold_hits_array[threshold].mean()) if threshold.any() else None,
        "date_bootstrap": bootstrap_masked_rate(dates, threshold_hits_array, threshold, schedule),
    }

    def residual_summary(values: Sequence[float]) -> dict[str, float]:
        arr=np.asarray(values,dtype=float)
        return {"mean_signed":float(arr.mean()),"median_signed":float(np.median(arr)),
                "mean_absolute":float(np.mean(np.abs(arr))),"p95_absolute":float(np.quantile(np.abs(arr),.95))}

    subgroup_rows=[]
    for year in sorted(set(years)):
        for distance in sorted({distances[i] for i,y in enumerate(years) if y==year}):
            include=np.asarray([(years[i]==year and distances[i]==distance) for i in range(len(race_ids))],dtype=bool)
            record={"evaluation_year":year,"distance_m":distance,"races":int(include.sum()),
                    "race_dates":int(len({dates[i] for i in range(len(dates)) if include[i]})),"policies":{}}
            for name, values in selected_hits.items():
                vector=np.asarray(values,dtype=float)
                record["policies"][name]={"hits":int(vector[include].sum()),"hit_rate":float(vector[include].mean()),
                    "date_bootstrap":bootstrap_masked_rate(dates,vector,include,schedule)}
            subgroup_rows.append(record)

    return {
        "races": len(race_ids),
        "race_dates": len(unique_dates),
        "selected_pair_hit_rates": hit_rates,
        "selected_pair_date_bootstrap": bootstrap,
        "all_pair_calibration": all_pair_metric,
        "selected_pair_calibration": selected_metric,
        "all_pair_reliability": all_pair_reliability,
        "selected_pair_reliability": selected_reliability,
        "selected_probability_ge_0_20": threshold_report,
        "sum_calibrated_pair_probability_minus_3": {
            "candidate": residual_summary(candidate_sum_residual),
            "baseline": residual_summary(baseline_sum_residual),
        },
        "year_distance": subgroup_rows,
        "selector_pairs": {
            "candidate": candidate_pair_by_race,
            "baseline": baseline_pair_by_race,
        },
    }


def verify_prediction_records(
    stored_rows: Sequence[Mapping[str, Any]],
    reproduced_rows: Sequence[Mapping[str, Any]],
    *,
    key_fields: Sequence[str],
    numeric_fields: Sequence[str],
    exact_fields: Sequence[str] = (),
    atol: float = 1e-12,
    rtol: float = 1e-12,
) -> dict[str, Any]:
    """Compare a saved all-pair table with independent reconstructed rows."""
    def indexed(rows: Sequence[Mapping[str, Any]], label: str) -> dict[tuple[Any, ...], Mapping[str, Any]]:
        result: dict[tuple[Any, ...], Mapping[str, Any]] = {}
        for row in rows:
            key = tuple(row[field] for field in key_fields)
            require(key not in result, f"duplicate {label} prediction key: {key!r}")
            result[key] = row
        return result

    saved = indexed(stored_rows, "stored")
    rebuilt = indexed(reproduced_rows, "reproduced")
    require(saved.keys() == rebuilt.keys(), "stored/reproduced all-pair key sets differ")
    maximum_errors: dict[str, float] = {field: 0.0 for field in numeric_fields}
    for key in sorted(saved):
        for field in exact_fields:
            require(saved[key][field] == rebuilt[key][field], f"stored/reproduced {field} mismatch at {key!r}")
        for field in numeric_fields:
            left = float(saved[key][field])
            right = float(rebuilt[key][field])
            require(math.isfinite(left) and math.isfinite(right), f"non-finite {field} at {key!r}")
            difference = abs(left - right)
            maximum_errors[field] = max(maximum_errors[field], difference)
            require(math.isclose(left, right, rel_tol=rtol, abs_tol=atol), f"stored/reproduced {field} mismatch at {key!r}: {left!r} vs {right!r}")
    return {"rows": len(saved), "keys": list(key_fields), "max_abs_error": maximum_errors, "exact_fields": list(exact_fields)}


def approval_gate(receipt_path: Path, *, expected_plan_sha256: str, expected_contract_sha256: str) -> dict[str, Any]:
    """Require a matching explicit root fit approval before any data load."""
    candidate = Path(receipt_path)
    require(not candidate.is_symlink(), "fit-approval receipt must not be a symlink")
    require(candidate.is_file(), "root fit-approval receipt is required before source/outcome reproduction")
    resolved = candidate.resolve(strict=True)
    review_dir = Path(__file__).resolve().parent
    study_dir = review_dir.with_name("20261011_pair_top3_direct_v1")
    allowed_dirs = (review_dir, study_dir)
    require(any(resolved.is_relative_to(directory.resolve(strict=True)) for directory in allowed_dirs),
            "fit-approval receipt must be under the locked pair-study or review directory")
    import json

    receipt=json.loads(resolved.read_text(encoding="utf-8"))
    explicit = (
        receipt.get("approved") is True
        and receipt.get("approved_by") == "root"
        and receipt.get("scope") in {"fit_and_evaluate", "fit", "direct_pair_fit"}
        and receipt.get("plan_sha256") == expected_plan_sha256
        and receipt.get("input_contract_sha256") == expected_contract_sha256
    )
    consumed_root_gate = (
        receipt.get("status") == "CONDITIONAL_FIT_AUTHORIZATION_CONSUMED"
        and receipt.get("study") == "20261011_pair_top3_direct_v1"
        and "Root approved the single prescribed 3 H1 + 6 H2 fits" in str(receipt.get("authorizing_root_message", ""))
        and receipt.get("structural_preflight_status") == "PASS"
        and receipt.get("frozen_design_artifacts", {}).get("jeju/research/20261011_pair_top3_direct_v1/PLAN.md") == expected_plan_sha256
        and receipt.get("frozen_design_artifacts", {}).get("jeju/research/20261011_pair_top3_direct_v1/INPUT_CONTRACT.md") == expected_contract_sha256
        and receipt.get("same_fold_evaluation_labels_used_for_fit") is False
        and receipt.get("performance_metrics_computed") is False
    )
    require(explicit or consumed_root_gate, "fit approval receipt does not evidence matching root authorization")
    return receipt


def assert_close(left: Sequence[float], right: Sequence[float], *, atol: float = 1e-12, rtol: float = 1e-12, label: str) -> float:
    a=np.asarray(left,dtype=float);b=np.asarray(right,dtype=float)
    require(a.shape==b.shape,f"{label}: shape mismatch {a.shape} vs {b.shape}")
    diff=np.abs(a-b)
    require(np.allclose(a,b,atol=atol,rtol=rtol),f"{label}: arrays differ; max abs diff={float(diff.max(initial=0.0))}")
    return float(diff.max(initial=0.0))


def synthetic_self_test() -> dict[str, Any]:
    """Run pure synthetic checks only; no source files and no optimizer calls."""
    rng=np.random.default_rng(20261011)
    a=rng.normal(size=7);b=rng.normal(size=7);ma=np.asarray([0.,1.,0.]);mb=np.asarray([1.,0.,1.])
    swap_equal=np.array_equal(symmetric_basis(a,b,ma,mb),symmetric_basis(b,a,mb,ma))
    require(swap_equal,"pair basis is not invariant to horse swap")
    cases=0
    for scores in ([.8,.8,.2,-.1],[1.,1.,1.,0.,-.5],rng.normal(size=12).tolist()):
        numbers=list(range(1,len(scores)+1))
        pairs,p0,_=exact_top3_pair_prior(numbers,scores)
        chosen=choose_pair(pairs,p0)
        raw=tuple(sorted(sorted(numbers,key=lambda n:(-float(scores[n-1]),n))[:2]))
        require(chosen==raw,"synthetic q0 selector differs from raw top two")
        cases+=1
    h1_x=[rng.normal(size=(8,20)),rng.normal(size=(11,20))]
    h1_p=[rng.uniform(.03,.95,size=len(x)) for x in h1_x]
    h1_y=[rng.integers(0,2,size=len(x)).astype(float) for x in h1_x]
    beta=rng.normal(scale=.07,size=20)
    h1_value,h1_grad=h1_objective_gradient(beta,h1_x,h1_p,h1_y)
    fd_h1=np.empty(20)
    eps=1e-6
    for j in range(20):
        plus=beta.copy();minus=beta.copy();plus[j]+=eps;minus[j]-=eps
        fd_h1[j]=(h1_objective_gradient(plus,h1_x,h1_p,h1_y)[0]-h1_objective_gradient(minus,h1_x,h1_p,h1_y)[0])/(2*eps)
    h1_grad_error=float(np.max(np.abs(fd_h1-h1_grad)))
    require(h1_grad_error<1e-7 and math.isfinite(h1_value),"synthetic independent H1 gradient check failed")
    h2_u=[rng.normal(size=9),rng.normal(size=13)]
    h2_y=[rng.integers(0,2,size=len(x)).astype(float) for x in h2_u]
    theta=np.asarray([.2,1.3])
    h2_value,h2_grad=platt_objective_gradient(theta,h2_u,h2_y)
    fd_h2=np.empty(2)
    for j in range(2):
        plus=theta.copy();minus=theta.copy();plus[j]+=eps;minus[j]-=eps
        fd_h2[j]=(platt_objective_gradient(plus,h2_u,h2_y)[0]-platt_objective_gradient(minus,h2_u,h2_y)[0])/(2*eps)
    h2_grad_error=float(np.max(np.abs(fd_h2-h2_grad)))
    require(h2_grad_error<1e-7 and math.isfinite(h2_value),"synthetic independent H2 gradient check failed")
    projected=projected_box_gradient((-20.,20.),(.4,-.3))
    wrong_way=projected_box_gradient((-20.,20.),(-.4,.3))
    require(np.array_equal(projected,np.asarray([0.,0.])) and np.array_equal(wrong_way,np.asarray([-.4,.3])),
            "synthetic projected gradient boundary sign mismatch")
    bootstrap = paired_date_bootstrap(
        ["2026-01-01", "2026-01-01", "2026-01-02"],
        {"candidate": [1.0, 0.0, 1.0], "baseline": [0.0, 0.0, 1.0]},
        reference="baseline",
        n_resamples=128,
        seed=20261011,
    )
    require(bootstrap["candidate"]["difference"]["estimate"] == 1.0 / 3.0, "synthetic paired bootstrap point difference mismatch")
    subset = paired_date_bootstrap(
        ["2026-01-01", "2026-01-02"],
        {"threshold": [1.0, 0.0]},
        valid_by_method={"threshold": [True, False]},
        n_resamples=128,
        seed=20261011,
    )
    require(subset["threshold"]["estimate"] == 1.0 and subset["threshold"]["undefined_resamples"] > 0,
            "synthetic fixed-subset bootstrap behavior mismatch")
    global_schedule=make_date_bootstrap_schedule(["2026-01-01","2026-01-01","2026-01-02"],n_resamples=128)
    masked=bootstrap_masked_rate(["2026-01-01","2026-01-02"],[1.,0.],[True,False],global_schedule)
    require(masked["estimate"]==1. and masked["undefined_resamples"]>0,"synthetic shared-schedule subset behavior mismatch")
    return {"pair_swap_exact":True,"q0_raw_top2_cases":cases,
            "h1_gradient_max_abs_error":h1_grad_error,"h2_gradient_max_abs_error":h2_grad_error,
            "projected_gradient_boundary_signs":True,"bootstrap_paired_dates":True,
            "bootstrap_fixed_subset_undefined_count":subset["threshold"]["undefined_resamples"],
            "global_bootstrap_schedule":date_bootstrap_schedule_receipt(global_schedule),
            "global_bootstrap_subset_undefined_count":masked["undefined_resamples"],
            "optimizer_calls":0,"source_data_read":False,"outcomes_calculated":False}


if __name__ == "__main__":
    print(synthetic_self_test())
