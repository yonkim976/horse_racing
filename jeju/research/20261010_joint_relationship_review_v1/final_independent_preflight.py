"""Independent, outcome-free verification of the finalized A preflight.

This module does not import implementation helpers. It reconstructs the source
lock, calibration boundaries, scorer roster, baseline six tickets, runner
scaler, pair projection, and race-balanced pair RMS from locked raw sources.
It does not fit coefficients, optimize temperatures, or calculate performance
metrics. Its only write target is this review folder's new final receipt.
"""
from __future__ import annotations

from datetime import date, timedelta
from hashlib import sha256
from itertools import combinations
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
IMPLEMENTATION = ROOT / "jeju/research/20261010_joint_relationship_v1"
STYLE_OUT = ROOT / "jeju/research/20261010_style_history_ablation_v1/outputs"
INITIAL_RECEIPT = HERE / "outputs/initial_preflight.json"
INITIAL_SCRIPT = HERE / "preflight.py"
FINAL_RECEIPT = HERE / "outputs/independent_preflight_final.json"
PLAN_SHA256 = "e0a34c6962112d88bfec7e645efbd8e4ea69bf4aada088f580e1188bac1207f3"
INITIAL_RECEIPT_SHA256 = "e6cfc37a8170bc9eaa36a7aae44c2cd2819d309359e21c67b1ae78258799262c"
INITIAL_SCRIPT_SHA256 = "8d9a2e20ff546a8f2f5a228b4259aa76d9164af2c22be0dc198f07823a54a233"
YEARS = (2024, 2025, 2026)
EXPECTED_COHORT = {"races": 1779, "runner_rows": 17412, "race_days": 269, "triples": 201404}
EXPECTED_SPLITS = {
    2024: {"h1_races": 312, "h2_races": 336, "purged_races": 9,
           "h1_max": "2023-06-24", "h2_min": "2023-07-01", "min_field": 8},
    2025: {"h1_races": 326, "h2_races": 311, "purged_races": 0,
           "h1_max": "2024-06-29", "h2_min": "2024-07-05", "min_field": 8},
    2026: {"h1_races": 329, "h2_races": 325, "purged_races": 0,
           "h1_max": "2025-06-28", "h2_min": "2025-07-04", "min_field": 7},
}
INPUT_COLUMNS = (
    "score",
    "hist_s1f_relpos_mean5", "hist_s1f_relpos_n",
    "hist_s1f_to_c4_forward_mean5", "hist_s1f_to_c4_pair_n",
    "hist_c4_to_g1f_forward_mean5", "hist_c4_to_g1f_pair_n",
)
MEAN_COLUMNS = (
    "hist_s1f_relpos_mean5",
    "hist_s1f_to_c4_forward_mean5",
    "hist_c4_to_g1f_forward_mean5",
)
COUNT_FOR_MEAN = {
    "hist_s1f_relpos_mean5": "hist_s1f_relpos_n",
    "hist_s1f_to_c4_forward_mean5": "hist_s1f_to_c4_pair_n",
    "hist_c4_to_g1f_forward_mean5": "hist_c4_to_g1f_pair_n",
}
DEGENERATE_TOL = 1e-12
PROJECTION_TOL = 1e-10


def confined(path: Path, *, must_exist: bool = True) -> Path:
    resolved = path.resolve(strict=must_exist)
    resolved.relative_to(ROOT)
    return resolved


def digest(path: Path) -> str:
    path = confined(path)
    value = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(confined(path).read_text(encoding="utf-8"))


def assert_close(actual, expected, *, atol: float = 1e-12, rtol: float = 1e-10, label: str):
    if not np.allclose(np.asarray(actual, dtype=np.float64),
                       np.asarray(expected, dtype=np.float64), atol=atol, rtol=rtol):
        raise AssertionError(f"independent value differs from A receipt: {label}")


def verify_a_source_lock() -> tuple[dict, dict, dict[str, str]]:
    plan_path = IMPLEMENTATION / "PLAN.md"
    source_lock_path = IMPLEMENTATION / "outputs/source_lock.json"
    preflight_path = IMPLEMENTATION / "outputs/preflight_receipt.json"
    if digest(plan_path) != PLAN_SHA256:
        raise AssertionError("root-approved plan hash changed")
    if digest(INITIAL_RECEIPT) != INITIAL_RECEIPT_SHA256:
        raise AssertionError("frozen initial C preflight receipt changed")
    if digest(INITIAL_SCRIPT) != INITIAL_SCRIPT_SHA256:
        raise AssertionError("frozen initial C preflight code changed")

    source_lock = read_json(source_lock_path)
    a_preflight = read_json(preflight_path)
    if source_lock.get("plan_sha256") != PLAN_SHA256 or a_preflight.get("plan_sha256") != PLAN_SHA256:
        raise AssertionError("A source lock/preflight does not name the approved plan")
    if a_preflight.get("passed") is not True:
        raise AssertionError("A preflight did not pass")
    if a_preflight.get("source_lock_sha256") != digest(source_lock_path):
        raise AssertionError("A source lock and preflight receipt hash do not match")
    if a_preflight.get("outcome_metrics_computed") is not False:
        raise AssertionError("A structural preflight must not claim outcome metrics")
    if a_preflight.get("relationship_coefficients_fitted") is not False:
        raise AssertionError("A structural preflight must not fit coefficients")
    if a_preflight.get("temperature_optimized") is not False:
        raise AssertionError("A structural preflight must not optimize temperatures")

    source_hashes: dict[str, str] = {}
    for relative, record in source_lock.get("sources", {}).items():
        path = confined(ROOT / relative)
        actual = digest(path)
        if actual != record.get("sha256"):
            raise AssertionError(f"locked source changed: {relative}")
        expected = record.get("expected_sha256")
        if expected is not None and actual != expected:
            raise AssertionError(f"manifest source hash changed: {relative}")
        for reference in record.get("verified_references", []):
            if reference.get("sha256") != actual:
                raise AssertionError(f"source reference hash differs: {relative}")
        source_hashes[relative] = actual
    if not source_hashes:
        raise AssertionError("A source lock contains no sources")

    initial = read_json(INITIAL_RECEIPT)
    if initial.get("status") != "PASS" or initial.get("candidate_pair_model_fit") is not False:
        raise AssertionError("frozen C initial preflight receipt is invalid")
    if initial.get("new_outcome_performance_metrics_computed") is not False:
        raise AssertionError("frozen C initial preflight contains outcome performance metrics")
    return source_lock, a_preflight, source_hashes


def load_feature_data() -> pd.DataFrame:
    columns = [
        "api_record_id", "race_id", "race_date", "year", "distance_m", "horse_id",
        "horse_number", "field_n", "finish_position", "history_cutoff", "latest_history_date",
        *INPUT_COLUMNS[1:],
    ]
    features = pd.read_parquet(confined(STYLE_OUT / "features.parquet"), columns=columns)
    if len(features) != 52155 or features.api_record_id.isna().any() or features.api_record_id.duplicated().any():
        raise AssertionError("locked feature table row/key contract failed")
    features["api_record_id"] = features.api_record_id.astype("int64")
    features["year"] = pd.to_numeric(features.year, errors="raise").astype("int64")
    features["race_date"] = pd.to_datetime(features.race_date, errors="raise").dt.normalize()
    features["horse_number"] = pd.to_numeric(features.horse_number, errors="raise").astype("int64")
    features["field_n"] = pd.to_numeric(features.field_n, errors="raise").astype("int64")
    features["finish_position"] = pd.to_numeric(features.finish_position, errors="raise").astype("int64")
    return features


def attach_scores(features: pd.DataFrame, year: int, role: str, expected_rows: int) -> pd.DataFrame:
    folder = STYLE_OUT / f"F1_STYLE6_{year}"
    path = folder / ("calibration_scores.parquet" if role == "calibration" else "evaluation_scores.parquet")
    score = pd.read_parquet(confined(path), columns=["api_record_id", "score"])
    if list(score.columns) != ["api_record_id", "score"]:
        raise AssertionError(f"score schema mismatch: {path}")
    score["api_record_id"] = pd.to_numeric(score.api_record_id, errors="raise").astype("int64")
    score["score"] = pd.to_numeric(score.score, errors="raise").astype("float64")
    if len(score) != expected_rows or score.api_record_id.isna().any() or score.api_record_id.duplicated().any():
        raise AssertionError(f"saved {role} score row/key contract failed for {year}")
    target_year = year - 1 if role == "calibration" else year
    frame = features.loc[features.year.eq(target_year)].copy()
    if len(frame) != expected_rows or set(frame.api_record_id) != set(score.api_record_id):
        raise AssertionError(f"saved {role} scores do not exactly cover feature keys for {year}")
    mapped = score.set_index("api_record_id").score
    frame["score"] = frame.api_record_id.map(mapped)
    if frame.score.isna().any() or not np.isfinite(frame.score.to_numpy(float)).all():
        raise AssertionError(f"saved {role} score join contains invalid values for {year}")
    frame["race_date"] = pd.to_datetime(frame.race_date, errors="raise").dt.normalize()
    return frame.sort_values(["race_id", "horse_number"], kind="stable").reset_index(drop=True)


def assert_history_and_roster(frame: pd.DataFrame, *, labels: bool) -> list[pd.DataFrame]:
    race_dates = pd.to_datetime(frame.race_date, errors="raise").dt.normalize()
    cutoff = pd.to_datetime(frame.history_cutoff, errors="raise").dt.normalize()
    latest = pd.to_datetime(frame.latest_history_date, errors="coerce").dt.normalize()
    if not cutoff.equals(race_dates - pd.Timedelta(days=2)):
        raise AssertionError("stored history cutoff differs from race_date minus 2 days")
    if (latest.notna() & latest.gt(cutoff)).any():
        raise AssertionError("stored latest history date violates race T-2 cutoff")
    groups = []
    for race_id, group in frame.groupby("race_id", sort=True, observed=True):
        group = group.sort_values("horse_number", kind="stable").reset_index(drop=True)
        n = len(group)
        if n < 5 or math.comb(n, 3) < 6:
            raise AssertionError(f"six-ticket support invalid at {race_id}")
        if group.race_date.nunique() != 1 or group.horse_id.nunique() != n or group.horse_number.nunique() != n:
            raise AssertionError(f"race roster identity/date mismatch at {race_id}")
        if not group.field_n.eq(n).all():
            raise AssertionError(f"field_n does not equal race roster size at {race_id}")
        if labels:
            finish = group.finish_position.to_numpy(int)
            if not np.array_equal(np.sort(finish), np.arange(1, n + 1)):
                raise AssertionError(f"finish ranks are not one unique 1..N permutation at {race_id}")
            if set(finish[finish <= 3].tolist()) != {1, 2, 3}:
                raise AssertionError(f"Top3 label is not the unordered rank set 1/2/3 at {race_id}")
        groups.append(group)
    if not groups:
        raise AssertionError("race group set is empty")
    return groups


def split_fold(calibration: pd.DataFrame, evaluation: pd.DataFrame, meta: dict, year: int) -> dict:
    cal_dates = pd.to_datetime(calibration.race_date).dt.normalize()
    eval_dates = pd.to_datetime(evaluation.race_date).dt.normalize()
    declared = {
        "calibration_min": cal_dates.min(), "calibration_max": cal_dates.max(),
        "evaluation_min": eval_dates.min(), "evaluation_max": eval_dates.max(),
    }
    for key, actual in declared.items():
        if pd.Timestamp(meta[key]).normalize() != actual:
            raise AssertionError(f"saved meta date mismatch: {year} {key}")
    h1_initial = calibration.loc[cal_dates.dt.month.le(6)].copy()
    h2 = calibration.loc[cal_dates.dt.month.ge(7)].copy()
    if h1_initial.empty or h2.empty:
        raise AssertionError(f"empty H1/H2 block for {year}")
    h2_min = pd.to_datetime(h2.race_date).dt.normalize().min()
    h1_cutoff = h2_min - pd.Timedelta(days=2)
    h1_dates = pd.to_datetime(h1_initial.race_date).dt.normalize()
    keep = h1_dates.le(h1_cutoff)
    h1 = h1_initial.loc[keep].copy()
    purged = h1_initial.loc[~keep].copy()
    if h1.empty:
        raise AssertionError(f"H1 empty after T-2 purge for {year}")
    refit_max = pd.Timestamp(meta["refit_max"]).normalize()
    h1_min = pd.to_datetime(h1.race_date).dt.normalize().min()
    h1_max = pd.to_datetime(h1.race_date).dt.normalize().max()
    h2_max = pd.to_datetime(h2.race_date).dt.normalize().max()
    eval_min = eval_dates.min()
    gaps = {"refit_to_h1_days": (h1_min - refit_max).days,
            "h1_to_h2_days": (h2_min - h1_max).days,
            "h2_to_evaluation_days": (eval_min - h2_max).days}
    if min(gaps.values()) < 2:
        raise AssertionError(f"T-2 chronological boundary failed for {year}: {gaps}")
    expected = EXPECTED_SPLITS[year]
    h1_n = h1.groupby("race_id", sort=False).size()
    h2_n = h2.groupby("race_id", sort=False).size()
    purge_n = purged.groupby("race_id", sort=False).size()
    if (len(h1_n), len(h2_n), len(purge_n)) != (expected["h1_races"], expected["h2_races"], expected["purged_races"]):
        raise AssertionError(f"H1/H2/purge race counts differ from frozen expectations for {year}")
    if str(h1_max.date()) != expected["h1_max"] or str(h2_min.date()) != expected["h2_min"]:
        raise AssertionError(f"H1/H2 actual boundary dates differ from frozen expectations for {year}")
    min_field = min(int(h1_n.min()), int(h2_n.min()))
    if min_field != expected["min_field"]:
        raise AssertionError(f"H1/H2 minimum field size differs for {year}")
    return {"h1": h1.reset_index(drop=True), "h2": h2.reset_index(drop=True),
            "purged": purged.reset_index(drop=True), "h1_max": h1_max, "h2_min": h2_min,
            "h2_max": h2_max, "eval_min": eval_min, "refit_max": refit_max,
            "gaps": gaps, "h1_groups": assert_history_and_roster(h1, labels=True),
            "h2_groups": assert_history_and_roster(h2, labels=True),
            "eval_groups": assert_history_and_roster(evaluation, labels=True),
            "min_field_h1": int(h1_n.min()), "min_field_h2": int(h2_n.min())}


def fit_scaler(frame: pd.DataFrame) -> dict:
    stats: dict[str, dict] = {}
    weights = 1.0 / pd.to_numeric(frame.field_n, errors="raise").to_numpy(float)
    for name in INPUT_COLUMNS:
        raw = pd.to_numeric(frame[name], errors="coerce").to_numpy(float)
        if name in MEAN_COLUMNS:
            support = pd.to_numeric(frame[COUNT_FOR_MEAN[name]], errors="raise").to_numpy(float)
            valid = (support > 0) & np.isfinite(raw)
        else:
            valid = np.isfinite(raw)
        denominator = float(weights[valid].sum())
        if denominator <= 0:
            stats[name] = {"mean": 0.0, "sd": 0.0, "valid_weight_sum": denominator,
                           "valid_rows": int(valid.sum()), "degenerate": True}
            continue
        mean = float(np.sum(weights[valid] * raw[valid]) / denominator)
        variance = float(np.sum(weights[valid] * (raw[valid] - mean) ** 2) / denominator)
        sd_raw = math.sqrt(max(variance, 0.0))
        degenerate = sd_raw <= DEGENERATE_TOL
        stats[name] = {"mean": mean, "sd": 0.0 if degenerate else sd_raw,
                       "valid_weight_sum": denominator, "valid_rows": int(valid.sum()),
                       "degenerate": bool(degenerate)}
    return stats


def transform_runner(group: pd.DataFrame, scaler: dict) -> tuple[np.ndarray, np.ndarray]:
    values = np.zeros((len(group), len(INPUT_COLUMNS)), dtype=np.float64)
    valid = np.ones_like(values, dtype=bool)
    for col, name in enumerate(INPUT_COLUMNS):
        raw = pd.to_numeric(group[name], errors="coerce").to_numpy(float)
        if name in MEAN_COLUMNS:
            support = pd.to_numeric(group[COUNT_FOR_MEAN[name]], errors="raise").to_numpy(float)
            valid[:, col] = (support > 0) & np.isfinite(raw)
        else:
            valid[:, col] = np.isfinite(raw)
        if not scaler[name]["degenerate"]:
            values[valid[:, col], col] = (raw[valid[:, col]] - scaler[name]["mean"]) / scaler[name]["sd"]
    if not np.isfinite(values).all():
        raise AssertionError("standardized input contains non-finite values")
    return values, valid


def pair_basis(values: np.ndarray, valid: np.ndarray) -> tuple[list[tuple[int, int]], np.ndarray]:
    pairs = list(combinations(range(len(values)), 2))
    left = np.fromiter((p[0] for p in pairs), dtype=np.int64)
    right = np.fromiter((p[1] for p in pairs), dtype=np.int64)
    cols = [values[left, 0] * values[right, 0]]
    for k, name in enumerate(INPUT_COLUMNS):
        diff = np.abs(values[left, k] - values[right, k])
        if name in MEAN_COLUMNS:
            support = valid[left, k] & valid[right, k]
            diff[~support] = 0.0
        cols.append(diff)
    for name in MEAN_COLUMNS:
        k = INPUT_COLUMNS.index(name)
        cols.append((~(valid[left, k] & valid[right, k])).astype(np.float64))
    phi = np.column_stack(cols).astype(np.float64, copy=False)
    return pairs, phi


def project_pairs(pairs: list[tuple[int, int]], phi: np.ndarray, n: int) -> tuple[np.ndarray, np.ndarray]:
    degree = np.zeros((n, phi.shape[1]), dtype=np.float64)
    for row, (i, j) in enumerate(pairs):
        degree[i] += phi[row]
        degree[j] += phi[row]
    total = phi.sum(axis=0)
    unary = (degree - total / (n - 1)) / (n - 2)
    residual = np.asarray([phi[r] - unary[i] - unary[j]
                           for r, (i, j) in enumerate(pairs)], dtype=np.float64)
    row_sums = np.zeros_like(degree)
    for row, (i, j) in enumerate(pairs):
        row_sums[i] += residual[row]
        row_sums[j] += residual[row]
    if np.max(np.abs(row_sums)) > PROJECTION_TOL:
        raise AssertionError("independently recomputed pair residual violates zero row-sum")
    return residual, row_sums


def triple_rows(pairs: list[tuple[int, int]], triples: list[tuple[int, int, int]]) -> np.ndarray:
    lookup = {pair: row for row, pair in enumerate(pairs)}
    output = np.empty((len(triples), 3), dtype=np.int64)
    for row, (i, j, k) in enumerate(triples):
        output[row] = (lookup[(i, j)], lookup[(i, k)], lookup[(j, k)])
    return output


def projection_stats(group: pd.DataFrame, scaler: dict, pair_rms: np.ndarray) -> dict:
    values, valid = transform_runner(group, scaler)
    pairs, phi = pair_basis(values, valid)
    residual, row_sums = project_pairs(pairs, phi, len(group))
    normalized = np.zeros_like(residual)
    active = pair_rms > DEGENERATE_TOL
    normalized[:, active] = residual[:, active] / pair_rms[active]
    maxima = np.max(np.abs(normalized), axis=0)
    normalized[:, maxima <= DEGENERATE_TOL] = 0.0
    triples = list(combinations(range(len(group)), 3))
    pair_at_triple = triple_rows(pairs, triples)
    g = normalized[pair_at_triple].sum(axis=1)
    incidence = np.zeros((len(triples), len(group)), dtype=np.float64)
    incidence[np.arange(len(triples))[:, None], np.asarray(triples)] = 1.0
    return {"max_row_sum_abs": float(np.max(np.abs(row_sums))),
            "max_A_transpose_G_abs": float(np.max(np.abs(incidence.T @ g))),
            "preclean_max_abs": maxima.tolist(), "triple_count": len(triples)}


def baseline_energy(scores: np.ndarray, triples: list[tuple[int, int, int]]) -> np.ndarray:
    ids = np.asarray(triples, dtype=np.int64)
    return np.sort(scores[ids], axis=1).sum(axis=1)


def baseline_six(groups: list[pd.DataFrame]) -> dict:
    saved = pd.read_csv(confined(STYLE_OUT / "report/canonical_six_combinations.csv"),
                        usecols=["race_id", "variant", "selection_rank", "numbers"],
                        dtype={"race_id": "string", "variant": "string", "numbers": "string"})
    saved = saved.loc[saved.variant.eq("F1_STYLE6")].copy()
    saved["selection_rank"] = pd.to_numeric(saved.selection_rank, errors="raise").astype("int64")
    saved = saved.sort_values(["race_id", "selection_rank"], kind="stable").reset_index(drop=True)
    actual = []
    tie_races = 0
    for group in groups:
        triples = list(combinations(range(len(group)), 3))
        energy = baseline_energy(group.score.to_numpy(float), triples)
        tie_races += int(len(np.unique(energy)) < len(energy))
        order = np.argsort(-energy, kind="stable")[:6]
        numbers = group.horse_number.to_numpy(int)
        for rank, index in enumerate(order, 1):
            ticket = ",".join(str(value) for value in sorted(numbers[list(triples[index])]))
            actual.append({"race_id": str(group.race_id.iloc[0]), "selection_rank": rank, "numbers": ticket})
    recreated = pd.DataFrame(actual).sort_values(["race_id", "selection_rank"], kind="stable").reset_index(drop=True)
    recreated = recreated.astype({"race_id": "string", "selection_rank": "int64", "numbers": "string"})
    if not recreated.equals(saved[["race_id", "selection_rank", "numbers"]].astype(
            {"race_id": "string", "selection_rank": "int64", "numbers": "string"})):
        raise AssertionError("independent F1_STYLE6 zero-residual six parity failed")
    return {"passed": True, "race_count": int(len(groups)), "ticket_rows": int(len(recreated)),
            "exact_saved_order_parity": True, "races_with_energy_ties": tie_races}


def synthetic_pair_projection_control() -> dict:
    n = 7
    unary = np.asarray([-0.4, 0.2, 1.1, -0.7, 0.5, 0.9, -0.1], dtype=np.float64)
    pairs = list(combinations(range(n), 2))
    additive = np.asarray([unary[i] + unary[j] for i, j in pairs])
    additive_matrix = additive[:, None]
    additive_residual, _ = project_pairs(pairs, additive_matrix, n)
    altered = additive.copy()
    pair_01 = pairs.index((0, 1))
    altered[pair_01] += 0.75
    pair_residual, _ = project_pairs(pairs, altered[:, None], n)
    if np.max(np.abs(additive_residual)) > 1e-12 or np.linalg.norm(pair_residual) <= 1e-6:
        raise AssertionError("synthetic unary-only/pair perturbation control failed")
    return {"unary_additive_residual_max_abs": float(np.max(np.abs(additive_residual))),
            "genuine_pair_perturbation_residual_l2": float(np.linalg.norm(pair_residual)),
            "unary_projects_to_zero": True, "genuine_pair_survives": True}


def compare_a_fold(a_fold: dict, year: int, scaler: dict, pair_rms: np.ndarray,
                   h1_stats: list[dict], h2_stats: list[dict], eval_stats: list[dict]) -> None:
    assert a_fold["evaluation_year"] == year
    if list(a_fold["pair_features"]) != [
            "score_product", "absdiff_score", "absdiff_hist_s1f_relpos_mean5",
            "absdiff_hist_s1f_relpos_n", "absdiff_hist_s1f_to_c4_forward_mean5",
            "absdiff_hist_s1f_to_c4_pair_n", "absdiff_hist_c4_to_g1f_forward_mean5",
            "absdiff_hist_c4_to_g1f_pair_n", "missing_either_hist_s1f_relpos_mean5",
            "missing_either_hist_s1f_to_c4_forward_mean5", "missing_either_hist_c4_to_g1f_forward_mean5"]:
        raise AssertionError(f"pair feature order mismatch in A preflight for {year}")
    active = np.flatnonzero(pair_rms > DEGENERATE_TOL).tolist()
    if list(a_fold["active_pair_columns"]) != active:
        raise AssertionError(f"active pair columns differ from independent recomputation for {year}")
    assert_close(a_fold["pair_rms"], pair_rms, label=f"pair_rms/{year}")
    for name in INPUT_COLUMNS:
        for key in ("mean", "sd", "valid_weight_sum"):
            assert_close(scaler[name][key], a_fold["runner_scaler"][name][key], label=f"scaler/{year}/{name}/{key}")
        if scaler[name]["valid_rows"] != a_fold["runner_scaler"][name]["valid_rows"]:
            raise AssertionError(f"scaler valid row count differs: {year}/{name}")
        if scaler[name]["degenerate"] != a_fold["runner_scaler"][name]["degenerate"]:
            raise AssertionError(f"scaler degeneracy differs: {year}/{name}")
    for key, ours, theirs in (("h1_projection", h1_stats, a_fold["h1_projection"]),
                              ("h2_projection", h2_stats, a_fold["h2_projection"]),
                              ("evaluation_projection", eval_stats, a_fold["evaluation_projection"])):
        if len(ours) != theirs["race_groups"]:
            raise AssertionError(f"projection race group count differs: {year}/{key}")
        if max(item["max_row_sum_abs"] for item in ours) > PROJECTION_TOL:
            raise AssertionError(f"independent projection row sums exceed tolerance: {year}/{key}")
        if max(item["max_A_transpose_G_abs"] for item in ours) > PROJECTION_TOL:
            raise AssertionError(f"independent triple unary orthogonality exceeds tolerance: {year}/{key}")
        assert_close(max(item["max_row_sum_abs"] for item in ours),
                     theirs["max_pair_residual_row_sum_abs"], atol=PROJECTION_TOL,
                     label=f"projection-rowmax/{year}/{key}")
        assert_close(max(item["max_A_transpose_G_abs"] for item in ours),
                     theirs["max_A_transpose_G_abs"], atol=PROJECTION_TOL,
                     label=f"projection-AtransposeG/{year}/{key}")


def main() -> None:
    if FINAL_RECEIPT.exists():
        raise FileExistsError(f"refusing to overwrite final independent receipt: {FINAL_RECEIPT}")
    source_lock, a_receipt, locked_hashes_before = verify_a_source_lock()
    features = load_feature_data()
    all_eval_groups: list[pd.DataFrame] = []
    fold_records = []
    triple_sum = race_sum = row_sum = 0
    all_eval_days: set[str] = set()
    a_folds = {int(fold["evaluation_year"]): fold for fold in a_receipt["folds"]}
    if set(a_folds) != set(YEARS):
        raise AssertionError("A preflight folds do not cover the three fixed evaluation years")

    for year in YEARS:
        meta = read_json(STYLE_OUT / f"F1_STYLE6_{year}/meta.json")
        calibration = attach_scores(features, year, "calibration", int(meta["calibration_rows"]))
        evaluation = attach_scores(features, year, "evaluation", int(meta["evaluation_rows"]))
        split = split_fold(calibration, evaluation, meta, year)
        scaler = fit_scaler(split["h1"])
        h1_race_residual_means = []
        for group in split["h1_groups"]:
            values, valid = transform_runner(group, scaler)
            pairs, phi = pair_basis(values, valid)
            residual, _ = project_pairs(pairs, phi, len(group))
            h1_race_residual_means.append(np.mean(residual * residual, axis=0))
        pair_rms = np.sqrt(np.mean(np.vstack(h1_race_residual_means), axis=0))
        h1_stats = [projection_stats(group, scaler, pair_rms) for group in split["h1_groups"]]
        h2_stats = [projection_stats(group, scaler, pair_rms) for group in split["h2_groups"]]
        eval_stats = [projection_stats(group, scaler, pair_rms) for group in split["eval_groups"]]
        compare_a_fold(a_folds[year], year, scaler, pair_rms, h1_stats, h2_stats, eval_stats)

        current_races = len(split["eval_groups"])
        current_rows = len(evaluation)
        current_triples = sum(math.comb(len(group), 3) for group in split["eval_groups"])
        triple_sum += current_triples
        race_sum += current_races
        row_sum += current_rows
        all_eval_days.update(pd.to_datetime(evaluation.race_date).dt.strftime("%Y-%m-%d").unique())
        all_eval_groups.extend(split["eval_groups"])
        fold_records.append({
            "evaluation_year": year,
            "calibration_year": year - 1,
            "h1_races_after_purge": len(split["h1_groups"]),
            "h2_races": len(split["h2_groups"]),
            "h1_purged_races": int(split["purged"].race_id.nunique()),
            "h1_last_date": str(split["h1_max"].date()),
            "h2_first_date": str(split["h2_min"].date()),
            "h2_last_date": str(split["h2_max"].date()),
            "evaluation_first_date": str(split["eval_min"].date()),
            "minimum_field_size_h1_h2": [split["min_field_h1"], split["min_field_h2"]],
            "t_minus_2_gaps_days": split["gaps"],
            "h1_scaler_and_pair_rms_match_A_preflight": True,
            "pair_projection_group_counts": {
                "h1": len(h1_stats), "h2": len(h2_stats), "evaluation": len(eval_stats)},
            "projection_row_sum_and_A_transpose_G_tolerance_pass": True,
        })

    if (race_sum, row_sum, len(all_eval_days), triple_sum) != (
            EXPECTED_COHORT["races"], EXPECTED_COHORT["runner_rows"],
            EXPECTED_COHORT["race_days"], EXPECTED_COHORT["triples"]):
        raise AssertionError("independent frozen evaluation cohort does not match the contract")
    parity = baseline_six(all_eval_groups)
    if parity["ticket_rows"] != race_sum * 6:
        raise AssertionError("independent baseline ticket count is not exactly six per race")
    synthetic = synthetic_pair_projection_control()

    if (a_receipt["evaluation"] != {
            "races": EXPECTED_COHORT["races"], "runner_rows": EXPECTED_COHORT["runner_rows"],
            "race_days": EXPECTED_COHORT["race_days"], "all_triples": EXPECTED_COHORT["triples"],
            "unique_race_ids": EXPECTED_COHORT["races"], "six_tickets": EXPECTED_COHORT["races"] * 6}):
        raise AssertionError("A preflight evaluation cohort receipt differs from independently reconstructed cohort")
    if a_receipt.get("saved_baseline_six_parity", {}).get("passed") is not True:
        raise AssertionError("A preflight did not report passing saved baseline-six parity")

    locked_hashes_after = {relative: digest(ROOT / relative) for relative in locked_hashes_before}
    if locked_hashes_after != locked_hashes_before:
        raise AssertionError("a locked source changed during independent final preflight")
    source_lock_path = IMPLEMENTATION / "outputs/source_lock.json"
    a_preflight_path = IMPLEMENTATION / "outputs/preflight_receipt.json"
    receipt = {
        "passed": True,
        "mode": "independent outcome-free structural verification",
        "study": "20261010_joint_relationship_review_v1",
        "plan_sha256": PLAN_SHA256,
        "source_lock_sha256": digest(source_lock_path),
        "preflight_receipt_sha256": digest(a_preflight_path),
        "frozen_initial_preflight_receipt_sha256": INITIAL_RECEIPT_SHA256,
        "frozen_initial_preflight_script_sha256": INITIAL_SCRIPT_SHA256,
        "reviewer_source_path": str(Path(__file__).resolve().relative_to(ROOT)),
        "reviewer_script_sha256": digest(Path(__file__)),
        "source_hashes_unchanged_during_verification": True,
        "checked_locked_source_count": len(locked_hashes_before),
        "locked_source_hashes": locked_hashes_before,
        "database_query_or_connection": False,
        "protected_database_read_only_hash_only": True,
        "network_access": False,
        "evaluation_cohort": {"races": race_sum, "runner_rows": row_sum,
                              "race_days": len(all_eval_days), "all_triples": triple_sum,
                              "six_ticket_rows": parity["ticket_rows"]},
        "fold_boundaries": fold_records,
        "zero_residual_f1_style6_six_parity": parity,
        "synthetic_pair_projection_negative_control": synthetic,
        "new_outcome_performance_metrics_computed": False,
        "relationship_coefficients_fitted": False,
        "temperature_optimized": False,
    }
    FINAL_RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    with FINAL_RECEIPT.open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
    print(json.dumps({
        "passed": receipt["passed"],
        "receipt": str(FINAL_RECEIPT.relative_to(ROOT)),
        "receipt_sha256": digest(FINAL_RECEIPT),
        "reviewer_script_sha256": receipt["reviewer_script_sha256"],
        "locked_sources": receipt["checked_locked_source_count"],
        "evaluation_cohort": receipt["evaluation_cohort"],
        "six_parity": parity["exact_saved_order_parity"],
        "outcome_performance_metrics": receipt["new_outcome_performance_metrics_computed"],
        "model_fit": receipt["relationship_coefficients_fitted"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
