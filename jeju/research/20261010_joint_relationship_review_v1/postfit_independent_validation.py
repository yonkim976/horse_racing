"""Independent post-fit reconstruction for the F1_STYLE6 relationship study.

This file deliberately does not import code from the implementation study. It
reconstructs saved-parameter diagnostics and evaluation distributions from the
locked raw inputs. Running it requires the explicit execution flag because the
post-fit path computes outcome metrics. It never fits coefficients or searches
for temperatures.
"""
from __future__ import annotations

from hashlib import sha256
from itertools import combinations
import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from scipy.special import logsumexp


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
A = ROOT / "jeju/research/20261010_joint_relationship_v1"
A_OUT = A / "outputs"
STYLE_OUT = ROOT / "jeju/research/20261010_style_history_ablation_v1/outputs"
GAP_OUT = ROOT / "jeju/research/20261010_probability_combo_gap_v1/outputs"
C_PREFLIGHT = HERE / "outputs/independent_preflight_final.json"
PLAN_SHA256 = "e0a34c6962112d88bfec7e645efbd8e4ea69bf4aada088f580e1188bac1207f3"
INITIAL_C_SHA256 = "e6cfc37a8170bc9eaa36a7aae44c2cd2819d309359e21c67b1ae78258799262c"
FINAL_C_SHA256 = "8d2b7ad7d32fe31685906c5197ec486e9e0cc64200e08947b39d0e613436afde"
EXPECTED_A_LOCK_SHA256 = "4e5acda8590e8ab415be45333a8bd26f8894a390f411b33ce669e439d565fb61"
EXPECTED_A_PREFLIGHT_SHA256 = "4fdaa44bcb0a440201ce3ac6d3c67ee3ae4009cc07e34b39fe6124ddee450e3e"
EXPECTED_A_VERIFY_SHA256 = "a0f87d1ec7e8a16aa8c48fcae7c47de14b171711455fd575605c4b8059da3346"
EXPECTED_C_ACCEPT_SHA256 = "597ddbcbf595b28b95fadc47a6bd0ff321809c2502805bd2991bbbb5281a431f"
EXPECTED_ROOT_APPROVAL_SHA256 = "419c0cb0ed6c6e6cf1c08a2d0f5838a3cf507fb14e323731bcd6c12d06a02785"
EXPECTED_FIT_PARAMETERS_SHA256 = "ff96e32cc4e0c991ac1326ef111a785b0e4f11b49daedc9f584be00dfe72eaeb"
EXPECTED_FIT_RECEIPT_SHA256 = "8470f4d5848e12824511e3a6b03b2f481f760dcb7c433b59624894a8482b61dc"
EXPECTED_COHORT = {"races": 1779, "runner_rows": 17412, "race_days": 269,
                   "triples": 201404, "six_rows": 10674}
YEARS = (2024, 2025, 2026)
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
PAIR_FEATURES = (
    "score_product",
    *(f"absdiff_{name}" for name in INPUT_COLUMNS),
    *(f"missing_either_{name}" for name in MEAN_COLUMNS),
)
DEGENERATE_TOL = 1e-12
PROJECTION_TOL = 1e-10
TEMP_BOUNDS = (0.35, 4.0)
BOOTSTRAP_DRAWS = 2000
BOOTSTRAP_SEED = 20261008
NUMERIC_ATOL = 1e-12
NUMERIC_RTOL = 1e-10


def confined(path: Path, *, must_exist: bool = True) -> Path:
    resolved = Path(path).resolve(strict=must_exist)
    try:
        resolved.relative_to(ROOT)
    except ValueError as exc:
        raise ValueError(f"path escapes the repository root: {path}") from exc
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


def assert_close(actual, expected, *, label: str, atol: float = NUMERIC_ATOL,
                 rtol: float = NUMERIC_RTOL) -> float:
    left = np.asarray(actual, dtype=np.float64)
    right = np.asarray(expected, dtype=np.float64)
    if left.shape != right.shape or not np.allclose(left, right, atol=atol, rtol=rtol,
                                                    equal_nan=False):
        if left.shape == right.shape and left.size:
            delta = float(np.max(np.abs(left - right)))
        else:
            delta = math.inf
        raise AssertionError(f"numeric mismatch for {label}: shape={left.shape}/{right.shape}, max_abs={delta}")
    return float(np.max(np.abs(left - right))) if left.size else 0.0


def verify_gate_artifacts() -> dict:
    plan_path = A / "PLAN.md"
    lock_path = A_OUT / "source_lock.json"
    preflight_path = A_OUT / "preflight_receipt.json"
    c_copy_path = A_OUT / "independent_preflight_receipt.json"
    c_accept_path = A_OUT / "c_preflight_acceptance.json"
    a_verify_path = A_OUT / "a_verification_receipt.json"
    approval_path = A_OUT / "root_fit_approval.json"
    params_path = A_OUT / "fit_parameters.json"
    fit_receipt_path = A_OUT / "fit_receipt.json"
    report_dir = A_OUT / "report"
    report_receipt_path = report_dir / "report_receipt.json"
    report_metrics_path = report_dir / "report_metrics.json"

    required = [plan_path, lock_path, preflight_path, c_copy_path, c_accept_path,
                a_verify_path, approval_path, params_path, fit_receipt_path,
                report_receipt_path, report_metrics_path,
                report_dir / "race_metrics.csv", report_dir / "runner_marginals.csv",
                report_dir / "all_triples.parquet"]
    missing = [str(path.relative_to(ROOT)) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"immutable fit/report artifacts are not complete: {missing}")

    if digest(plan_path) != PLAN_SHA256:
        raise AssertionError("approved PLAN hash changed")
    if digest(C_PREFLIGHT) != digest(c_copy_path):
        raise AssertionError("A's accepted copy is not byte-identical to the frozen C preflight")
    c_initial = read_json(HERE / "outputs/initial_preflight.json")
    if (digest(HERE / "outputs/initial_preflight.json") != INITIAL_C_SHA256 or
            (c_initial.get("passed") is not True and c_initial.get("status") != "PASS")):
        raise AssertionError("frozen initial C preflight changed or did not pass")

    lock = read_json(lock_path)
    preflight = read_json(preflight_path)
    independent = read_json(c_copy_path)
    acceptance = read_json(c_accept_path)
    a_verification = read_json(a_verify_path)
    approval = read_json(approval_path)
    parameters = read_json(params_path)
    fit_receipt = read_json(fit_receipt_path)
    report_receipt = read_json(report_receipt_path)
    report_metrics = read_json(report_metrics_path)

    lock_sha = digest(lock_path)
    preflight_sha = digest(preflight_path)
    c_sha = digest(c_copy_path)
    approval_sha = digest(approval_path)
    params_sha = digest(params_path)
    fit_receipt_sha = digest(fit_receipt_path)
    report_receipt_sha = digest(report_receipt_path)

    fixed_hashes = {
        "A source lock": (lock_sha, EXPECTED_A_LOCK_SHA256),
        "A preflight receipt": (preflight_sha, EXPECTED_A_PREFLIGHT_SHA256),
        "C final preflight": (c_sha, FINAL_C_SHA256),
        "A verification receipt": (digest(a_verify_path), EXPECTED_A_VERIFY_SHA256),
        "A C-acceptance receipt": (digest(c_accept_path), EXPECTED_C_ACCEPT_SHA256),
        "root fit approval": (approval_sha, EXPECTED_ROOT_APPROVAL_SHA256),
        "fit parameters": (params_sha, EXPECTED_FIT_PARAMETERS_SHA256),
        "fit receipt": (fit_receipt_sha, EXPECTED_FIT_RECEIPT_SHA256),
    }
    for label, (actual, expected) in fixed_hashes.items():
        if actual != expected:
            raise AssertionError(f"frozen {label} hash mismatch: {actual}")

    if lock.get("plan_sha256") != PLAN_SHA256 or preflight.get("plan_sha256") != PLAN_SHA256:
        raise AssertionError("A source lock/preflight does not name the approved plan")
    if preflight.get("passed") is not True or preflight.get("source_lock_sha256") != lock_sha:
        raise AssertionError("A preflight does not pass or does not match its source lock")
    if independent.get("passed") is not True or independent.get("plan_sha256") != PLAN_SHA256:
        raise AssertionError("C independent preflight is not passing for the approved plan")
    if independent.get("source_lock_sha256") != lock_sha or independent.get("preflight_receipt_sha256") != preflight_sha:
        raise AssertionError("C preflight receipt names different A gate artifacts")
    if acceptance.get("passed") is not True or acceptance.get("c_sha256") != c_sha:
        raise AssertionError("A did not byte-copy and accept the final C preflight receipt")
    if acceptance.get("a_copy_sha256") != digest(c_copy_path):
        raise AssertionError("A accepted preflight copy digest mismatch")
    if a_verification.get("passed") is not True:
        raise AssertionError("A structural verification receipt does not pass")
    if approval.get("approved") is not True or approval.get("approved_by") != "root":
        raise PermissionError("root fit approval artifact is not explicit")
    if approval.get("scope") != "fit_h1_relationship_and_h2_temperature_only":
        raise PermissionError("root fit approval has an unexpected scope")
    if (approval.get("plan_sha256") != PLAN_SHA256 or
            approval.get("source_lock_sha256") != lock_sha or
            approval.get("preflight_receipt_sha256") != preflight_sha or
            approval.get("independent_preflight_receipt_sha256") != c_sha):
        raise AssertionError("root fit approval names different frozen artifacts")
    if parameters.get("plan_sha256") != PLAN_SHA256 or parameters.get("source_lock_sha256") != lock_sha:
        raise AssertionError("saved fit parameters name different plan/source lock")
    if parameters.get("preflight_receipt_sha256") != preflight_sha:
        raise AssertionError("saved fit parameters name a different A preflight")
    if parameters.get("approval_sha256") != approval_sha:
        raise AssertionError("saved fit parameters do not bind the root fit approval")
    if parameters.get("independent_preflight_receipt_sha256") != c_sha:
        raise AssertionError("saved fit parameters do not bind C's accepted preflight")
    if fit_receipt.get("passed") is not True or fit_receipt.get("parameters_sha256") != params_sha:
        raise AssertionError("fit receipt does not validate the immutable fit parameters")
    if report_receipt.get("passed") is not True or report_receipt.get("fit_parameters_sha256") != params_sha:
        raise AssertionError("report receipt does not validate the immutable fit parameters")
    if report_receipt.get("outcome_metrics_computed_after_fit_artifact") is not True:
        raise AssertionError("report receipt does not establish post-fit-only outcome computation")
    for key, file_name in (("report_metrics_sha256", "report_metrics.json"),
                           ("race_metrics_sha256", "race_metrics.csv"),
                           ("runner_marginals_sha256", "runner_marginals.csv"),
                           ("all_triples_sha256", "all_triples.parquet")):
        if report_receipt.get(key) != digest(report_dir / file_name):
            raise AssertionError(f"A report receipt hash mismatch: {file_name}")
    if report_metrics.get("fit_parameters_sha256") != params_sha or report_metrics.get("fit_receipt_sha256") != fit_receipt_sha:
        raise AssertionError("A report metrics do not bind the immutable fit artifacts")

    source_hashes = {}
    for relative, record in lock.get("sources", {}).items():
        path = confined(ROOT / relative)
        actual = digest(path)
        if actual != record.get("sha256"):
            raise AssertionError(f"locked source changed after fit/report: {relative}")
        for declaration in record.get("verified_references", []):
            if declaration.get("sha256") != actual:
                raise AssertionError(f"frozen source declaration differs: {relative}")
        source_hashes[relative] = actual
    if parameters.get("source_hashes_before_fit") != source_hashes:
        raise AssertionError("fit parameters' before-fit source hashes differ from locked raw sources")
    if parameters.get("source_hashes_after_fit") != source_hashes:
        raise AssertionError("fit parameters' after-fit source hashes differ from locked raw sources")
    if parameters.get("source_hashes_unchanged_after_fit") is not True:
        raise AssertionError("fit parameters do not claim unchanged input sources")

    return {
        "source_lock": lock,
        "parameters": parameters,
        "fit_receipt": fit_receipt,
        "report_receipt": report_receipt,
        "report_metrics": report_metrics,
        "source_hashes": source_hashes,
        "hashes": {
            "plan_sha256": PLAN_SHA256,
            "source_lock_sha256": lock_sha,
            "preflight_receipt_sha256": preflight_sha,
            "independent_preflight_receipt_sha256": c_sha,
            "root_fit_approval_sha256": approval_sha,
            "fit_parameters_sha256": params_sha,
            "fit_receipt_sha256": fit_receipt_sha,
            "report_receipt_sha256": report_receipt_sha,
        },
    }


def load_feature_table() -> pd.DataFrame:
    path = STYLE_OUT / "features.parquet"
    frame = pd.read_parquet(confined(path))
    required = {"api_record_id", "race_id", "race_date", "year", "horse_id", "horse_number",
                "field_n", "finish_position", "distance_m", "history_cutoff",
                "latest_history_date", *INPUT_COLUMNS[1:]}
    missing = required.difference(frame.columns)
    if missing:
        raise AssertionError(f"locked raw feature table lacks required fields: {sorted(missing)}")
    if len(frame) != 52155 or frame.api_record_id.isna().any() or frame.api_record_id.duplicated().any():
        raise AssertionError("locked feature table row/key contract failed")
    frame["api_record_id"] = pd.to_numeric(frame.api_record_id, errors="raise").astype("int64")
    frame["year"] = pd.to_numeric(frame.year, errors="raise").astype("int64")
    frame["race_date"] = pd.to_datetime(frame.race_date, errors="raise").dt.normalize()
    frame["horse_number"] = pd.to_numeric(frame.horse_number, errors="raise").astype("int64")
    frame["field_n"] = pd.to_numeric(frame.field_n, errors="raise").astype("int64")
    frame["finish_position"] = pd.to_numeric(frame.finish_position, errors="raise").astype("int64")
    return frame


def attach_scores(features: pd.DataFrame, year: int, role: str, expected_rows: int) -> pd.DataFrame:
    folder = STYLE_OUT / f"F1_STYLE6_{year}"
    file_name = "calibration_scores.parquet" if role == "calibration" else "evaluation_scores.parquet"
    score_path = folder / file_name
    scores = pd.read_parquet(confined(score_path))
    if list(scores.columns) != ["api_record_id", "score"]:
        raise AssertionError(f"raw score schema mismatch: {score_path}")
    scores["api_record_id"] = pd.to_numeric(scores.api_record_id, errors="raise").astype("int64")
    scores["score"] = pd.to_numeric(scores.score, errors="raise").astype("float64")
    if len(scores) != expected_rows or scores.api_record_id.isna().any() or scores.api_record_id.duplicated().any():
        raise AssertionError(f"saved {role} raw score keys/row count invalid for {year}")
    target_year = year - 1 if role == "calibration" else year
    selected = features.loc[features.year.eq(target_year)].copy()
    if len(selected) != expected_rows or set(selected.api_record_id) != set(scores.api_record_id):
        raise AssertionError(f"saved {role} score keys do not exactly cover raw roster for {year}")
    score_map = scores.set_index("api_record_id").score
    selected["score"] = selected.api_record_id.map(score_map)
    if selected.score.isna().any() or not np.isfinite(selected.score.to_numpy(float)).all():
        raise AssertionError(f"saved {role} raw scores have missing/nonfinite values for {year}")
    selected["race_date"] = pd.to_datetime(selected.race_date, errors="raise").dt.normalize()
    return selected.sort_values(["race_id", "horse_number"], kind="stable").reset_index(drop=True)


def validate_rosters(frame: pd.DataFrame, *, validate_labels: bool = True) -> list[pd.DataFrame]:
    result = []
    for race_id, group in frame.groupby("race_id", sort=True, observed=True):
        group = group.sort_values("horse_number", kind="stable").reset_index(drop=True)
        n = len(group)
        if n < 5 or math.comb(n, 3) < 6:
            raise AssertionError(f"unsupported race roster {race_id}: N={n}")
        if group.horse_id.nunique() != n or group.horse_number.nunique() != n:
            raise AssertionError(f"duplicate horse identity/number in {race_id}")
        if not np.array_equal(group.field_n.to_numpy(int), np.full(n, n, dtype=int)):
            raise AssertionError(f"field_n differs from complete roster in {race_id}")
        if group.race_date.nunique() != 1:
            raise AssertionError(f"multiple race dates in {race_id}")
        if validate_labels:
            finish = group.finish_position.to_numpy(int)
            if not np.array_equal(np.sort(finish), np.arange(1, n + 1)):
                raise AssertionError(f"finish ranks are not a unique complete 1..N permutation: {race_id}")
            if set(finish[finish <= 3].tolist()) != {1, 2, 3}:
                raise AssertionError(f"top-3 labels are not exactly 1,2,3: {race_id}")
        result.append(group)
    return result


def split_calibration(cal: pd.DataFrame, evaluation: pd.DataFrame, meta: dict) -> dict:
    date = pd.to_datetime(cal.race_date, errors="raise").dt.normalize()
    eval_date = pd.to_datetime(evaluation.race_date, errors="raise").dt.normalize()
    if cal.empty or evaluation.empty:
        raise AssertionError("empty calibration or evaluation score frame")
    fields = {"calibration_min": date.min(), "calibration_max": date.max(),
              "evaluation_min": eval_date.min(), "evaluation_max": eval_date.max()}
    for name, actual in fields.items():
        if pd.Timestamp(meta[name]).normalize() != actual:
            raise AssertionError(f"raw-source boundary differs from saved meta {name}")
    h1_calendar = date.dt.month.le(6)
    h2_mask = date.dt.month.ge(7)
    if not h1_calendar.any() or not h2_mask.any():
        raise AssertionError("calendar H1/H2 split is empty")
    h2_first = date.loc[h2_mask].min()
    h1_cutoff = h2_first - pd.Timedelta(days=2)
    keep_h1 = h1_calendar & date.le(h1_cutoff)
    purge = h1_calendar & date.gt(h1_cutoff)
    h1 = cal.loc[keep_h1].copy().reset_index(drop=True)
    h2 = cal.loc[h2_mask].copy().reset_index(drop=True)
    dropped = cal.loc[purge].copy().reset_index(drop=True)
    if h1.empty or h2.empty:
        raise AssertionError("H1/H2 split empty after T-2 purge")
    h1_dates = pd.to_datetime(h1.race_date).dt.normalize()
    h2_dates = pd.to_datetime(h2.race_date).dt.normalize()
    eval_min = pd.to_datetime(evaluation.race_date).dt.normalize().min()
    refit_max = pd.Timestamp(meta["refit_max"]).normalize()
    if h1_dates.max() > h2_dates.min() - pd.Timedelta(days=2):
        raise AssertionError("H1 labels violate H2 T-2 purge")
    if h2_dates.max() > eval_min - pd.Timedelta(days=2):
        raise AssertionError("H2 labels violate evaluation T-2 gap")
    if refit_max > h1_dates.min() - pd.Timedelta(days=2):
        raise AssertionError("base refit_max violates H1 T-2 boundary")
    return {"h1": h1, "h2": h2, "purged": dropped,
            "h1_min": h1_dates.min(), "h1_max": h1_dates.max(),
            "h2_min": h2_dates.min(), "h2_max": h2_dates.max(),
            "eval_min": eval_min, "eval_max": pd.to_datetime(evaluation.race_date).dt.normalize().max(),
            "refit_max": refit_max,
            "h1_races": int(h1.race_id.nunique()), "h2_races": int(h2.race_id.nunique()),
            "purged_races": int(dropped.race_id.nunique())}


def fit_scaler(h1: pd.DataFrame) -> dict:
    stats = {}
    weight = 1.0 / pd.to_numeric(h1.field_n, errors="raise").to_numpy(float)
    for name in INPUT_COLUMNS:
        raw = pd.to_numeric(h1[name], errors="coerce").to_numpy(float)
        if name in MEAN_COLUMNS:
            count = pd.to_numeric(h1[COUNT_FOR_MEAN[name]], errors="raise").to_numpy(float)
            valid = (count > 0) & np.isfinite(raw)
        else:
            valid = np.isfinite(raw)
        denom = float(weight[valid].sum())
        if denom <= 0:
            stats[name] = {"mean": 0.0, "sd": 0.0, "valid_weight_sum": denom,
                           "valid_rows": int(valid.sum()), "degenerate": True}
            continue
        mean = float(np.sum(weight[valid] * raw[valid]) / denom)
        variance = float(np.sum(weight[valid] * np.square(raw[valid] - mean)) / denom)
        sd = math.sqrt(max(variance, 0.0))
        degenerate = sd <= DEGENERATE_TOL
        stats[name] = {"mean": mean, "sd": 0.0 if degenerate else sd,
                       "valid_weight_sum": denom, "valid_rows": int(valid.sum()),
                       "degenerate": bool(degenerate)}
    return stats


def transform_runner(group: pd.DataFrame, scaler: dict) -> tuple[np.ndarray, np.ndarray]:
    values = np.zeros((len(group), len(INPUT_COLUMNS)), dtype=np.float64)
    valid = np.ones(values.shape, dtype=bool)
    for col, name in enumerate(INPUT_COLUMNS):
        raw = pd.to_numeric(group[name], errors="coerce").to_numpy(float)
        if name in MEAN_COLUMNS:
            count = pd.to_numeric(group[COUNT_FOR_MEAN[name]], errors="raise").to_numpy(float)
            valid[:, col] = (count > 0) & np.isfinite(raw)
        else:
            valid[:, col] = np.isfinite(raw)
        stat = scaler[name]
        if not stat["degenerate"]:
            values[valid[:, col], col] = (raw[valid[:, col]] - float(stat["mean"])) / float(stat["sd"])
    if not np.isfinite(values).all():
        raise AssertionError("normalized runner features are non-finite")
    return values, valid


def pair_indices(n: int) -> np.ndarray:
    return np.asarray(list(combinations(range(n), 2)), dtype=np.int64)


def triple_indices(n: int) -> np.ndarray:
    return np.asarray(list(combinations(range(n), 3)), dtype=np.int64)


def pair_basis(values: np.ndarray, valid: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    pairs = pair_indices(values.shape[0])
    left, right = pairs[:, 0], pairs[:, 1]
    columns = [values[left, 0] * values[right, 0]]
    for col in range(values.shape[1]):
        delta = np.abs(values[left, col] - values[right, col])
        if INPUT_COLUMNS[col] in MEAN_COLUMNS:
            delta[~(valid[left, col] & valid[right, col])] = 0.0
        columns.append(delta)
    for name in MEAN_COLUMNS:
        col = INPUT_COLUMNS.index(name)
        columns.append((~(valid[left, col] & valid[right, col])).astype(np.float64))
    phi = np.column_stack(columns).astype(np.float64, copy=False)
    if phi.shape[1] != len(PAIR_FEATURES) or not np.isfinite(phi).all():
        raise AssertionError("pair basis contract failed")
    return pairs, phi


def project_pairs(pairs: np.ndarray, phi: np.ndarray, n: int) -> tuple[np.ndarray, np.ndarray]:
    if n < 3 or len(pairs) != math.comb(n, 2):
        raise AssertionError("pair incidence is incomplete")
    left, right = pairs[:, 0], pairs[:, 1]
    degree = np.zeros((n, phi.shape[1]), dtype=np.float64)
    for row, (i, j) in enumerate(pairs):
        degree[i] += phi[row]
        degree[j] += phi[row]
    total = phi.sum(axis=0)
    unary = (degree - total / (n - 1)) / (n - 2)
    residual = phi - unary[left] - unary[right]
    row_sums = np.zeros_like(degree)
    for row, (i, j) in enumerate(pairs):
        row_sums[i] += residual[row]
        row_sums[j] += residual[row]
    if np.max(np.abs(row_sums)) > PROJECTION_TOL:
        raise AssertionError("pair projection zero-row-sum condition failed")
    return residual, row_sums


def clean_residual(residual: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    cleaned = residual.copy()
    preclean = np.max(np.abs(cleaned), axis=0) if len(cleaned) else np.zeros(cleaned.shape[1])
    cleaned[:, preclean <= DEGENERATE_TOL] = 0.0
    return cleaned, preclean


def triple_pair_rows(pairs: np.ndarray, triples: np.ndarray) -> np.ndarray:
    lookup = {tuple(int(z) for z in pair): idx for idx, pair in enumerate(pairs.tolist())}
    rows = np.empty((len(triples), 3), dtype=np.int64)
    for idx, (i, j, k) in enumerate(triples):
        rows[idx, 0] = lookup[(int(i), int(j))]
        rows[idx, 1] = lookup[(int(i), int(k))]
        rows[idx, 2] = lookup[(int(j), int(k))]
    return rows


def relation_features(pairs: np.ndarray, residual: np.ndarray, triples: np.ndarray) -> np.ndarray:
    rows = triple_pair_rows(pairs, triples)
    # Keep the approved source arithmetic order: (i,j) + (i,k) + (j,k).
    return residual[rows[:, 0]] + residual[rows[:, 1]] + residual[rows[:, 2]]


def baseline_energy(scores: np.ndarray, triples: np.ndarray) -> np.ndarray:
    return np.sort(scores[triples], axis=1).sum(axis=1)


def softmax_energy(energy: np.ndarray, tau: float) -> np.ndarray:
    scaled = energy / float(tau)
    return np.exp(scaled - logsumexp(scaled))


def prediction_state(group: pd.DataFrame, scaler: dict, pair_rms: np.ndarray,
                     beta: np.ndarray) -> dict:
    # Canonical horse-number order is the tie-break basis; labels/IDs never enter energies.
    group = group.sort_values("horse_number", kind="stable").reset_index(drop=True)
    values, valid = transform_runner(group, scaler)
    pairs, phi = pair_basis(values, valid)
    residual, row_sums = project_pairs(pairs, phi, len(group))
    normalized = np.zeros_like(residual)
    active = pair_rms > DEGENERATE_TOL
    normalized[:, active] = residual[:, active] / pair_rms[active]
    cleaned, preclean = clean_residual(normalized)
    triples = triple_indices(len(group))
    x = relation_features(pairs, cleaned, triples)
    base = baseline_energy(group.score.to_numpy(float), triples)
    relation = x @ beta
    candidate = base + relation
    truth_rows = np.flatnonzero(group.finish_position.to_numpy(int) <= 3)
    truth_tuple = tuple(sorted(int(i) for i in truth_rows))
    truth_index = next((idx for idx, triple in enumerate(triples)
                        if tuple(int(i) for i in triple) == truth_tuple), None)
    if truth_index is None:
        raise AssertionError(f"truth set not found for race {group.race_id.iloc[0]}")
    incidence = np.zeros((len(triples), len(group)), dtype=np.float64)
    incidence[np.arange(len(triples))[:, None], triples] = 1.0
    orthogonal = incidence.T @ x
    return {"group": group, "pairs": pairs, "phi": phi, "residual": residual,
            "row_sums": row_sums, "preclean_max": preclean, "triples": triples,
            "x": x, "incidence_transpose_x": orthogonal,
            "baseline_energy": base, "relation_energy": relation,
            "candidate_energy": candidate, "truth_index": int(truth_index)}


def exact_objective(beta_active: np.ndarray, h1_data: list[dict], active: np.ndarray,
                    lam: float = 1.0) -> tuple[float, np.ndarray]:
    loss = 0.0
    gradient = np.zeros(len(active), dtype=np.float64)
    for race in h1_data:
        x = race["x"][:, active]
        e = race["baseline_energy"] + x @ beta_active
        log_z = float(logsumexp(e))
        p = np.exp(e - log_z)
        t = race["truth_index"]
        loss += log_z - float(e[t])
        gradient += p @ x - x[t]
    if not h1_data:
        raise AssertionError("empty H1 objective data")
    loss /= len(h1_data)
    gradient /= len(h1_data)
    return float(loss + 0.5 * lam * float(beta_active @ beta_active)), gradient + lam * beta_active


def finite_difference_gradient(beta: np.ndarray, fun, eps: float = 1e-6) -> np.ndarray:
    result = np.empty_like(beta, dtype=np.float64)
    for col in range(len(beta)):
        step = np.zeros_like(beta)
        step[col] = eps
        plus, _ = fun(beta + step)
        minus, _ = fun(beta - step)
        result[col] = (plus - minus) / (2.0 * eps)
    return result


def tau_objective(races: list[dict], energy_key: str, tau: float) -> float:
    losses = []
    for race in races:
        e = race[energy_key] / float(tau)
        losses.append(float(logsumexp(e) - e[race["truth_index"]]))
    return float(np.mean(losses))


def tau_gradient(races: list[dict], energy_key: str, tau: float) -> float:
    terms = []
    for race in races:
        energy = race[energy_key]
        p = softmax_energy(energy, tau)
        terms.append((float(energy[race["truth_index"]]) - float(p @ energy)) / (tau * tau))
    return float(np.mean(terms))


def make_h1_race(group: pd.DataFrame, scaler: dict, pair_rms: np.ndarray) -> dict:
    state = prediction_state(group, scaler, pair_rms, np.zeros(len(PAIR_FEATURES), dtype=np.float64))
    return {"x": state["x"], "baseline_energy": state["baseline_energy"],
            "truth_index": state["truth_index"]}


def reconstruct_fit_checks(features: pd.DataFrame, parameters: dict) -> tuple[dict, dict]:
    fold_checks = {}
    fold_context = {}
    for fold in parameters["folds"]:
        year = int(fold["evaluation_year"])
        if year not in YEARS:
            raise AssertionError(f"unexpected saved fit year: {year}")
        folder = STYLE_OUT / f"F1_STYLE6_{year}"
        meta = read_json(folder / "meta.json")
        calibration = attach_scores(features, year, "calibration", int(meta["calibration_rows"]))
        evaluation = attach_scores(features, year, "evaluation", int(meta["evaluation_rows"]))
        split = split_calibration(calibration, evaluation, meta)
        h1_groups = validate_rosters(split["h1"])
        h2_groups = validate_rosters(split["h2"])
        scaler = fit_scaler(split["h1"])
        saved_scaler = fold["runner_scaler"]
        scaler_maxdiff = 0.0
        for name in INPUT_COLUMNS:
            for field in ("mean", "sd", "valid_weight_sum"):
                scaler_maxdiff = max(scaler_maxdiff, assert_close(
                    [scaler[name][field]], [saved_scaler[name][field]],
                    label=f"{year} scaler {name}.{field}"))
            if scaler[name]["valid_rows"] != saved_scaler[name]["valid_rows"] or bool(
                    scaler[name]["degenerate"]) != bool(saved_scaler[name]["degenerate"]):
                raise AssertionError(f"{year} scaler support/degenerate mismatch for {name}")

        residual_moments = []
        raw_h1_states = []
        for group in h1_groups:
            values, valid = transform_runner(group, scaler)
            pairs, phi = pair_basis(values, valid)
            residual, row_sums = project_pairs(pairs, phi, len(group))
            if float(np.max(np.abs(row_sums))) > PROJECTION_TOL:
                raise AssertionError(f"{year} H1 projection row sum tolerance failed")
            residual_moments.append(np.mean(np.square(residual), axis=0))
            raw_h1_states.append((group, pairs, phi, residual))
        pair_rms = np.sqrt(np.mean(np.vstack(residual_moments), axis=0))
        rms_diff = assert_close(pair_rms, fold["pair_rms"], label=f"{year} race-equal pair RMS")
        active = np.flatnonzero(pair_rms > DEGENERATE_TOL)
        if active.tolist() != list(fold["active_columns"]):
            raise AssertionError(f"{year} active pair columns differ from saved parameters")

        h1_data = [make_h1_race(group, scaler, pair_rms) for group in h1_groups]
        beta_full = np.asarray(fold["beta"], dtype=np.float64)
        if beta_full.shape != (len(PAIR_FEATURES),) or not np.isfinite(beta_full).all():
            raise AssertionError(f"{year} saved beta vector has invalid shape/values")
        if not np.array_equal(np.flatnonzero(beta_full), active[np.flatnonzero(beta_full[active] != 0)]):
            # Inactive coefficients are required to be exactly zero; active coefficients may also be zero.
            if np.any(beta_full[np.setdiff1d(np.arange(len(PAIR_FEATURES)), active)] != 0.0):
                raise AssertionError(f"{year} inactive pair coefficients are not exact zero")
        fit = fold.get("fit", {})
        if fit.get("success") is not True or fit.get("optimizer_skipped") is True:
            if len(active):
                raise AssertionError(f"{year} coefficient fit did not record a successful optimizer")
        if list(fit.get("active_columns", active.tolist())) != active.tolist():
            raise AssertionError(f"{year} optimizer active columns differ")
        if len(active):
            beta_active = beta_full[active]
            objective, gradient = exact_objective(beta_active, h1_data, active)
            fun = lambda value: exact_objective(value, h1_data, active)
            fd = finite_difference_gradient(beta_active, fun)
            fd_max = float(np.max(np.abs(fd - gradient)))
            if fd_max > 2e-6:
                raise AssertionError(f"{year} H1 analytic gradient finite-difference check failed: {fd_max}")
            objective_diff = assert_close([objective], [fit["objective"]],
                                          label=f"{year} H1 saved objective", atol=2e-10, rtol=1e-10)
            grad_norm = float(np.max(np.abs(gradient)))
            if fit.get("gradient_inf_norm") is not None:
                assert_close([grad_norm], [fit["gradient_inf_norm"]],
                             label=f"{year} H1 saved gradient norm", atol=2e-7, rtol=1e-7)
            if grad_norm > 1e-5:
                raise AssertionError(f"{year} H1 saved beta fails stationarity threshold: {grad_norm}")
            norm = float(np.linalg.norm(gradient))
            perturb_deltas = []
            if norm > 0:
                for radius in (1e-5, 1e-4, 1e-3):
                    delta = -gradient / norm * radius
                    shifted, _ = exact_objective(beta_active + delta, h1_data, active)
                    perturb_deltas.append(shifted - objective)
                if min(perturb_deltas) < -1e-10:
                    raise AssertionError(f"{year} H1 local descent perturbation beats saved beta")
        else:
            objective, _ = exact_objective(beta_full, h1_data, active)
            fd_max = 0.0
            objective_diff = assert_close([objective], [fit["objective"]], label=f"{year} zero H1 objective")
            grad_norm = 0.0
            perturb_deltas = []

        h2_data = []
        for group in h2_groups:
            state = prediction_state(group, scaler, pair_rms, beta_full)
            h2_data.append({"baseline_energy": state["baseline_energy"],
                            "candidate_energy": state["candidate_energy"],
                            "truth_index": state["truth_index"]})
        tau_records = {}
        for name, energy_key in (("baseline_tau", "baseline_energy"),
                                 ("candidate_tau", "candidate_energy")):
            record = fold[name]
            tau = float(record["tau"])
            if not (TEMP_BOUNDS[0] <= tau <= TEMP_BOUNDS[1]) or not record.get("success", False):
                raise AssertionError(f"{year} {name} is outside bounds or was unsuccessful")
            nll = tau_objective(h2_data, energy_key, tau)
            nll_diff = assert_close([nll], [record["h2_nll"]],
                                    label=f"{year} {name} saved H2 NLL", atol=2e-10, rtol=1e-10)
            derivative = tau_gradient(h2_data, energy_key, tau)
            step = 1e-5
            plus = tau_objective(h2_data, energy_key, tau + step)
            minus = tau_objective(h2_data, energy_key, tau - step)
            fd_derivative = (plus - minus) / (2.0 * step)
            derivative_fd = abs(derivative - fd_derivative)
            if derivative_fd > 2e-6:
                raise AssertionError(f"{year} {name} temperature derivative finite-difference check failed")
            near = [tau_objective(h2_data, energy_key, tau + signed * epsilon)
                    for epsilon in (1e-4, 1e-3)
                    for signed in (-1.0, 1.0)
                    if TEMP_BOUNDS[0] < tau + signed * epsilon < TEMP_BOUNDS[1]]
            if near and min(near) < nll - 1e-10:
                raise AssertionError(f"{year} {name} saved temperature loses to local perturbation")
            if tau - TEMP_BOUNDS[0] > 1e-6 and TEMP_BOUNDS[1] - tau > 1e-6:
                if abs(derivative) > 2e-5:
                    raise AssertionError(f"{year} {name} interior KKT derivative too large: {derivative}")
                kkt = "interior_stationary"
            elif tau - TEMP_BOUNDS[0] <= 1e-6:
                if derivative < -2e-5:
                    raise AssertionError(f"{year} {name} lower-bound KKT direction failed")
                kkt = "lower_bound_direction"
            else:
                if derivative > 2e-5:
                    raise AssertionError(f"{year} {name} upper-bound KKT direction failed")
                kkt = "upper_bound_direction"
            tau_records[name] = {"tau": tau, "h2_nll": nll, "saved_nll_max_abs_diff": nll_diff,
                                 "analytic_derivative": derivative,
                                 "finite_difference_derivative": fd_derivative,
                                 "derivative_fd_abs_diff": derivative_fd,
                                 "kkt": kkt, "local_perturbation_nll": near,
                                 "temperature_optimizer_reexecuted": False}

        fold_checks[str(year)] = {
            "calibration_year": year - 1,
            "h1_races": len(h1_groups), "h2_races": len(h2_groups),
            "purged_races": split["purged_races"],
            "actual_dates": {key: str(split[key].date()) for key in
                             ("h1_min", "h1_max", "h2_min", "h2_max", "eval_min", "eval_max", "refit_max")},
            "t_minus_2_gaps_days": {
                "refit_to_h1_first": int((split["h1_min"] - split["refit_max"]).days),
                "h1_to_h2": int((split["h2_min"] - split["h1_max"]).days),
                "h2_to_eval": int((split["eval_min"] - split["h2_max"]).days),
            },
            "saved_scaler_max_abs_diff": scaler_maxdiff,
            "saved_pair_rms_max_abs_diff": rms_diff,
            "active_columns": active.tolist(),
            "beta": beta_full.tolist(),
            "h1_objective": objective,
            "h1_objective_max_abs_diff": objective_diff,
            "h1_gradient_inf_norm": grad_norm,
            "h1_gradient_fd_max_abs_diff": fd_max,
            "h1_local_descent_perturbation_objective_deltas": perturb_deltas,
            "h2_temperatures": tau_records,
        }
        fold_context[year] = {"evaluation": evaluation, "scaler": scaler,
                              "pair_rms": pair_rms, "beta": beta_full,
                              "baseline_tau": float(fold["baseline_tau"]["tau"]),
                              "candidate_tau": float(fold["candidate_tau"]["tau"]),
                              "saved_tau": float(meta["tau"]), "meta": meta}
    return fold_checks, fold_context


def probability_marginal(probability: np.ndarray, triples: np.ndarray, n: int) -> np.ndarray:
    marginal = np.zeros(n, dtype=np.float64)
    for col in range(3):
        np.add.at(marginal, triples[:, col], probability)
    return marginal


def selected_tickets(group: pd.DataFrame, triples: np.ndarray, energy: np.ndarray) -> tuple[np.ndarray, list[str]]:
    order = np.argsort(-energy, kind="stable")[:6]
    numbers = group.sort_values("horse_number", kind="stable").horse_number.to_numpy(int)
    tickets = [",".join(str(int(number)) for number in sorted(numbers[triples[index]])) for index in order]
    return order, tickets


def joint_brier(probability: np.ndarray, truth_index: int) -> float:
    onehot = np.eye(1, len(probability), int(truth_index))[0]
    return float(np.sum(np.square(probability - onehot)))


def race_prediction(group: pd.DataFrame, scaler: dict, pair_rms: np.ndarray,
                    beta: np.ndarray, baseline_tau: float, candidate_tau: float,
                    saved_tau: float) -> tuple[dict, list[dict], list[dict], dict]:
    state = prediction_state(group, scaler, pair_rms, beta)
    g = state["group"]
    triples = state["triples"]
    base = state["baseline_energy"]
    candidate = state["candidate_energy"]
    truth = state["truth_index"]
    arm_specs = (
        ("saved_original_tau", base, saved_tau, np.zeros(len(triples), dtype=np.float64)),
        ("matched_baseline", base, baseline_tau, np.zeros(len(triples), dtype=np.float64)),
        ("candidate", candidate, candidate_tau, state["relation_energy"]),
    )
    triple_rows = []
    arm_values = {}
    for arm, energy, tau, relation in arm_specs:
        probability = softmax_energy(energy, tau)
        order, tickets = selected_tickets(g, triples, energy)
        stable_order = np.argsort(-energy, kind="stable")
        ranks = np.empty(len(triples), dtype=np.int32)
        ranks[stable_order] = np.arange(1, len(triples) + 1, dtype=np.int32)
        marginal = probability_marginal(probability, triples, len(g))
        arm_values[arm] = {
            "energy": energy, "probability": probability, "order": order,
            "tickets": tickets, "ranks": ranks, "marginal": marginal,
            "true_nll": float(logsumexp(energy / tau) - energy[truth] / tau),
            "brier": joint_brier(probability, truth),
            "six_mass": float(probability[order].sum()),
            "hit6": int(any(set(triples[idx].tolist()) == set(triples[truth].tolist()) for idx in order)),
        }
        numbers = g.horse_number.to_numpy(int)
        for index, triple in enumerate(triples):
            ticket = ",".join(str(int(number)) for number in sorted(numbers[triple]))
            triple_rows.append({
                "race_id": str(g.race_id.iloc[0]),
                "race_date": str(pd.Timestamp(g.race_date.iloc[0]).date()),
                "evaluation_year": int(g.year.iloc[0]),
                "distance_m": int(g.distance_m.iloc[0]),
                "arm": arm,
                "triple_index": int(index),
                "triple_numbers": ticket,
                "baseline_score_energy": float(base[index]),
                "relationship_energy": float(relation[index]),
                "total_energy": float(energy[index]),
                "temperature": float(tau),
                "probability": float(probability[index]),
                "is_true_set": bool(index == truth),
                "canonical_rank": int(ranks[index]),
            })

    finish = g.finish_position.to_numpy(int)
    y = (finish <= 3).astype(np.int64)
    race_date = str(pd.Timestamp(g.race_date.iloc[0]).date())
    race_id = str(g.race_id.iloc[0])
    year = int(g.year.iloc[0])
    distance = float(g.distance_m.iloc[0])
    base_arm, candidate_arm = arm_values["matched_baseline"], arm_values["candidate"]
    race = {
        "race_id": race_id, "race_date": race_date, "evaluation_year": year,
        "distance_m": distance, "runner_rows": len(g), "triple_count": len(triples),
        "baseline_hit6": base_arm["hit6"], "candidate_hit6": candidate_arm["hit6"],
        "baseline_joint_true_set_nll": base_arm["true_nll"],
        "candidate_joint_true_set_nll": candidate_arm["true_nll"],
        "baseline_joint_brier": base_arm["brier"], "candidate_joint_brier": candidate_arm["brier"],
        "baseline_six_mass": base_arm["six_mass"], "candidate_six_mass": candidate_arm["six_mass"],
        # A's CSV serializes these Python lists via DataFrame.to_csv; retain the
        # same ordered list representation while checking exact tickets below.
        "baseline_six_tickets": str(base_arm["tickets"]),
        "candidate_six_tickets": str(candidate_arm["tickets"]),
        "delta_hit6": candidate_arm["hit6"] - base_arm["hit6"],
        "delta_joint_true_set_nll": candidate_arm["true_nll"] - base_arm["true_nll"],
    }
    runner_rows = []
    for idx, row in g.iterrows():
        runner_rows.append({
            "api_record_id": int(row.api_record_id), "race_id": race_id,
            "race_date": race_date, "evaluation_year": year,
            "horse_number": int(row.horse_number), "y_top3": int(y[idx]),
            "baseline_joint_marginal": float(base_arm["marginal"][idx]),
            "candidate_joint_marginal": float(candidate_arm["marginal"][idx]),
        })
    return race, runner_rows, triple_rows, {"state": state, "arms": arm_values}


def compare_dataframes(expected: pd.DataFrame, actual: pd.DataFrame, keys: list[str],
                       columns: list[str], label: str, *, float_tol: float = NUMERIC_ATOL) -> dict:
    if len(expected) != len(actual):
        raise AssertionError(f"{label} row count mismatch: C={len(expected)} A={len(actual)}")
    if expected.duplicated(keys).any() or actual.duplicated(keys).any():
        raise AssertionError(f"{label} comparison keys are not unique")
    joined = expected[keys + columns].merge(actual[keys + columns], on=keys, how="outer",
                                             suffixes=("_c", "_a"), validate="one_to_one",
                                             indicator=True)
    if not joined._merge.eq("both").all():
        raise AssertionError(f"{label} key coverage differs")
    maxdiff = {}
    for col in columns:
        left = joined[f"{col}_c"]
        right = joined[f"{col}_a"]
        if pd.api.types.is_numeric_dtype(left) and pd.api.types.is_numeric_dtype(right):
            x = left.to_numpy(dtype=np.float64)
            y = right.to_numpy(dtype=np.float64)
            delta = np.abs(x - y)
            maxdiff[col] = float(delta.max()) if len(delta) else 0.0
            if not np.allclose(x, y, atol=float_tol, rtol=NUMERIC_RTOL, equal_nan=False):
                raise AssertionError(f"{label}.{col} numeric mismatch max_abs={maxdiff[col]}")
        else:
            if not left.astype("string").equals(right.astype("string")):
                raise AssertionError(f"{label}.{col} categorical/keyed values differ")
            maxdiff[col] = 0.0
    return {"passed": True, "rows": int(len(expected)), "keys": keys,
            "max_abs_differences": maxdiff}


def bootstrap(frame: pd.DataFrame, column: str, expected_days: int | None = None) -> dict:
    daily = frame.groupby("race_date", as_index=False, observed=True)[column].agg(total="sum", races="size")
    if expected_days is not None and len(daily) != expected_days:
        raise AssertionError("paired date bootstrap has unexpected cluster count")
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    totals = daily.total.to_numpy(float)
    counts = daily.races.to_numpy(float)
    indices = rng.integers(0, len(daily), size=(BOOTSTRAP_DRAWS, len(daily)))
    values = totals[indices].sum(axis=1) / counts[indices].sum(axis=1)
    return {"estimate": float(frame[column].mean()),
            "ci95_low": float(np.quantile(values, 0.025)),
            "ci95_high": float(np.quantile(values, 0.975)),
            "draws": BOOTSTRAP_DRAWS, "seed": BOOTSTRAP_SEED, "cluster": "race_date"}


def aggregate_marginal(frame: pd.DataFrame, prediction: str) -> dict:
    y = frame.y_top3.to_numpy(float)
    p = np.clip(frame[prediction].to_numpy(float), 1e-15, 1.0 - 1e-15)
    losses = pd.DataFrame({"race_id": frame.race_id.to_numpy(),
                           "log_loss": -(y * np.log(p) + (1.0 - y) * np.log(1.0 - p)),
                           "brier": np.square(p - y)})
    per_race = losses.groupby("race_id", sort=True, observed=True)[["log_loss", "brier"]].mean()
    return {"runner_rows": int(len(frame)),
            "aggregation": {"primary": "mean of per-race runner-mean losses (strict race-equal)",
                            "runner_weighted_secondary": "mean over all runner rows"},
            "race_equal": {"races": int(len(per_race)),
                           "binary_log_loss": float(per_race.log_loss.mean()),
                           "brier": float(per_race.brier.mean())},
            "runner_weighted_secondary": {"binary_log_loss": float(losses.log_loss.mean()),
                                           "brier": float(losses.brier.mean())}}


def cohort_summary(group: pd.DataFrame, label: str, value: object) -> dict:
    return {label: value, "races": int(len(group)), "race_days": int(group.race_date.nunique()),
            "period_start": str(group.race_date.min()), "period_end": str(group.race_date.max()),
            "field_size_support": sorted(int(x) for x in group.runner_rows.unique()),
            "candidate_hit6": int(group.candidate_hit6.sum()),
            "baseline_hit6": int(group.baseline_hit6.sum()),
            "delta_hit6_mean": float(group.delta_hit6.mean()),
            "delta_hit6_paired_date_ci95": bootstrap(group, "delta_hit6"),
            "candidate_joint_true_set_nll": float(group.candidate_joint_true_set_nll.mean()),
            "baseline_joint_true_set_nll": float(group.baseline_joint_true_set_nll.mean()),
            "delta_joint_true_set_nll_mean": float(group.delta_joint_true_set_nll.mean()),
            "delta_joint_true_set_nll_paired_date_ci95": bootstrap(group, "delta_joint_true_set_nll")}


def independent_report_metrics(races: pd.DataFrame, runners: pd.DataFrame,
                               report_receipt: dict, parameters: dict,
                               fit_receipt: dict) -> dict:
    hit_ci = bootstrap(races, "delta_hit6", expected_days=EXPECTED_COHORT["race_days"])
    nll_ci = bootstrap(races, "delta_joint_true_set_nll", expected_days=EXPECTED_COHORT["race_days"])
    primary = {
        "comparison": "candidate - H2-matched raw-score baseline",
        "candidate_hit6_mean": float(races.candidate_hit6.mean()),
        "baseline_hit6_mean": float(races.baseline_hit6.mean()),
        "candidate_hit6_total": int(races.candidate_hit6.sum()),
        "baseline_hit6_total": int(races.baseline_hit6.sum()),
        "delta_hit6_mean": float(races.delta_hit6.mean()),
        "delta_hit6_date_bootstrap_95ci": hit_ci,
        "candidate_joint_true_set_nll_mean": float(races.candidate_joint_true_set_nll.mean()),
        "baseline_joint_true_set_nll_mean": float(races.baseline_joint_true_set_nll.mean()),
        "delta_joint_true_set_nll_mean": float(races.delta_joint_true_set_nll.mean()),
        "delta_joint_true_set_nll_date_bootstrap_95ci": nll_ci,
    }
    primary["research_signal_gate_passed"] = bool(
        primary["delta_hit6_mean"] > 0 and hit_ci["ci95_low"] > 0 and nll_ci["ci95_high"] <= 0)
    yearly = []
    for year, group in races.groupby("evaluation_year", sort=True):
        summary = cohort_summary(group, "evaluation_year", int(year))
        summary["partial_year"] = bool(int(year) == 2026)
        summary["candidate_joint_brier"] = float(group.candidate_joint_brier.mean())
        summary["baseline_joint_brier"] = float(group.baseline_joint_brier.mean())
        yearly.append(summary)
    distances = []
    for distance, group in races.groupby("distance_m", sort=True):
        summary = cohort_summary(group, "distance_m", int(distance))
        summary["candidate_joint_brier"] = float(group.candidate_joint_brier.mean())
        summary["baseline_joint_brier"] = float(group.baseline_joint_brier.mean())
        distances.append(summary)
    return {
        "study": "20261010_joint_relationship_v1",
        "plan_sha256": PLAN_SHA256,
        "fit_parameters_sha256": digest(A_OUT / "fit_parameters.json"),
        "fit_receipt_sha256": digest(A_OUT / "fit_receipt.json"),
        "preflight_receipt_sha256": digest(A_OUT / "preflight_receipt.json"),
        "evaluation_cohort": {"races": int(len(races)), "runner_rows": int(len(runners)),
                              "race_days": int(races.race_date.nunique()),
                              "start_date": str(races.race_date.min()), "end_date": str(races.race_date.max()),
                              "partial_year_2026": True},
        "all_triples_artifact": {"rows": int(2 * EXPECTED_COHORT["triples"]),
                                 "arms": {"candidate": EXPECTED_COHORT["triples"],
                                          "matched_baseline": EXPECTED_COHORT["triples"]},
                                 "columns": ["race_id", "race_date", "evaluation_year", "distance_m", "arm",
                                             "triple_index", "triple_numbers", "baseline_score_energy",
                                             "relationship_energy", "total_energy", "temperature", "probability",
                                             "is_true_set", "canonical_rank"]},
        "primary_gate": primary,
        "secondary_descriptive": {
            "overall_joint_brier": {"baseline": float(races.baseline_joint_brier.mean()),
                                    "candidate": float(races.candidate_joint_brier.mean())},
            "runner_marginal_log_loss_and_brier": {
                "h2_matched_baseline": aggregate_marginal(runners, "baseline_joint_marginal"),
                "candidate_joint_marginal": aggregate_marginal(runners, "candidate_joint_marginal"),
                "saved_f1_style6_runner_probability": aggregate_marginal(runners, "saved_f1_style6_p_top3")},
            "yearly": yearly,
            "distance_m": distances,
            "selected_six_mass_mean": {"baseline": float(races.baseline_six_mass.mean()),
                                       "candidate": float(races.candidate_six_mass.mean())},
        },
        "interpretation": "Retrospective repeated historical development cohort; no independent future holdout or operational promotion.",
        "fit_receipt": fit_receipt,
    }


def compare_nested(expected, actual, path: str = "report_metrics", *, atol: float = NUMERIC_ATOL) -> dict:
    if isinstance(expected, dict):
        if not isinstance(actual, dict) or set(expected) != set(actual):
            raise AssertionError(f"{path}: object keys differ")
        out = {}
        for key in expected:
            out.update(compare_nested(expected[key], actual[key], f"{path}.{key}", atol=atol))
        return out
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(expected) != len(actual):
            raise AssertionError(f"{path}: list lengths differ")
        out = {}
        for idx, (left, right) in enumerate(zip(expected, actual)):
            out.update(compare_nested(left, right, f"{path}[{idx}]", atol=atol))
        return out
    if isinstance(expected, bool) or isinstance(actual, bool):
        if expected is not actual:
            raise AssertionError(f"{path}: boolean differs: C={expected}, A={actual}")
        return {}
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        delta = abs(float(expected) - float(actual))
        if delta > atol + NUMERIC_RTOL * max(abs(float(expected)), abs(float(actual))):
            raise AssertionError(f"{path}: numeric mismatch: C={expected}, A={actual}, delta={delta}")
        return {path: delta}
    if expected != actual:
        raise AssertionError(f"{path}: value differs: C={expected!r}, A={actual!r}")
    return {}


def compare_saved_style_six(races: pd.DataFrame, baseline_tickets: dict[str, list[str]]) -> dict:
    saved_path = STYLE_OUT / "report/canonical_six_combinations.csv"
    saved = pd.read_csv(confined(saved_path), dtype={"race_id": "string", "numbers": "string"})
    if not {"race_id", "variant", "selection_rank", "numbers"}.issubset(saved.columns):
        raise AssertionError("saved canonical-six table schema mismatch")
    saved = saved.loc[saved.variant.eq("F1_STYLE6"), ["race_id", "selection_rank", "numbers"]].copy()
    saved["race_id"] = saved.race_id.astype("string")
    saved["selection_rank"] = pd.to_numeric(saved.selection_rank, errors="raise").astype(int)
    saved = saved.sort_values(["race_id", "selection_rank"], kind="stable").reset_index(drop=True)
    expected_rows = []
    for race_id, tickets in baseline_tickets.items():
        expected_rows.extend({"race_id": race_id, "selection_rank": rank, "numbers": ticket}
                             for rank, ticket in enumerate(tickets, 1))
    recreated = pd.DataFrame(expected_rows).astype({"race_id": "string", "selection_rank": "int64",
                                                     "numbers": "string"})
    if len(saved) != EXPECTED_COHORT["six_rows"] or len(recreated) != len(saved):
        raise AssertionError("saved F1_STYLE6 six-table row count differs")
    if not saved.equals(recreated.sort_values(["race_id", "selection_rank"], kind="stable").reset_index(drop=True)):
        raise AssertionError("independently selected H2-matched baseline six differs from frozen canonical six")
    if len(races) != EXPECTED_COHORT["races"]:
        raise AssertionError("race count differs for saved six parity")
    return {"passed": True, "races": int(len(races)), "ticket_rows": int(len(saved)),
            "exact_stable_order_parity": True}


def compare_original_saved_tau(saved_rows: pd.DataFrame) -> dict:
    path = GAP_OUT / "race_diagnostics.parquet"
    old = pd.read_parquet(confined(path))
    old = old.loc[old.variant.eq("F1_STYLE6")].copy()
    if old.race_id.duplicated().any() or len(old) != EXPECTED_COHORT["races"]:
        raise AssertionError("frozen probability-combo diagnostics do not have one F1_STYLE6 row per race")
    old = old.rename(columns={
        "year": "evaluation_year", "true_triple_rank": "true_rank", "six_hit": "hit6",
        "joint_true_nll_saved_tau": "joint_true_nll",
        "full_joint_brier_saved_tau": "full_joint_brier",
        "top3_marginal_log_loss_saved_tau": "marginal_log_loss",
        "top3_marginal_brier_saved_tau": "marginal_brier",
        "six_mass_saved_tau": "six_mass",
    })
    merged = saved_rows.merge(old, on="race_id", how="outer", suffixes=("_c", "_frozen"),
                              validate="one_to_one", indicator=True)
    if not merged._merge.eq("both").all():
        raise AssertionError("original saved-tau race keys differ from frozen diagnostics")
    fields = ["race_date", "evaluation_year", "distance_m", "true_rank", "hit6",
              "joint_true_nll", "full_joint_brier", "marginal_log_loss", "marginal_brier", "six_mass"]
    diffs = {}
    for col in fields:
        left, right = merged[f"{col}_c"], merged[f"{col}_frozen"]
        if col == "race_date":
            equal = left.astype("string").equals(right.astype("string"))
            delta = 0.0
        elif col in {"evaluation_year", "hit6", "true_rank"}:
            equal = np.array_equal(left.to_numpy(int), right.to_numpy(int))
            delta = 0.0 if equal else math.inf
        else:
            x, y = left.to_numpy(float), right.to_numpy(float)
            delta = float(np.max(np.abs(x - y)))
            equal = bool(np.allclose(x, y, atol=2e-12, rtol=NUMERIC_RTOL))
        if not equal:
            raise AssertionError(f"original saved-tau arm differs from frozen diagnostics at {col}: max_abs={delta}")
        diffs[col] = delta
    return {"passed": True, "races": int(len(old)), "frozen_diagnostic_sha256": digest(path),
            "fields_compared": fields, "max_abs_differences": diffs}


def invariance_checks(sample_group: pd.DataFrame, context: dict) -> dict:
    base = race_prediction(sample_group, context["scaler"], context["pair_rms"], context["beta"],
                          context["baseline_tau"], context["candidate_tau"], context["saved_tau"])[3]
    shuffled = sample_group.sample(frac=1.0, random_state=77331).reset_index(drop=True)
    permuted = race_prediction(shuffled, context["scaler"], context["pair_rms"], context["beta"],
                               context["baseline_tau"], context["candidate_tau"], context["saved_tau"])[3]
    perm_errors = {}
    for arm in ("saved_original_tau", "matched_baseline", "candidate"):
        left, right = base["arms"][arm], permuted["arms"][arm]
        perm_errors[f"{arm}_energy"] = assert_close(left["energy"], right["energy"], label=f"permutation {arm} energy", atol=0.0, rtol=0.0)
        perm_errors[f"{arm}_probability"] = assert_close(left["probability"], right["probability"], label=f"permutation {arm} probability", atol=0.0, rtol=0.0)
        if left["tickets"] != right["tickets"] or not np.array_equal(left["ranks"], right["ranks"]):
            raise AssertionError(f"canonical row permutation changed {arm} tickets/ranks")

    mutated = sample_group.copy()
    n = len(mutated)
    mutated["finish_position"] = np.arange(n, 0, -1, dtype=np.int64)
    mutated["api_record_id"] = mutated.api_record_id.astype("int64") + 900000000
    mutated["horse_id"] = [f"mutated-{i}" for i in range(n)]
    mutated["distance_m"] = -12345
    altered = race_prediction(mutated, context["scaler"], context["pair_rms"], context["beta"],
                              context["baseline_tau"], context["candidate_tau"], context["saved_tau"])[3]
    outcome_errors = {}
    for arm in ("saved_original_tau", "matched_baseline", "candidate"):
        left, right = base["arms"][arm], altered["arms"][arm]
        outcome_errors[f"{arm}_energy"] = assert_close(left["energy"], right["energy"], label=f"label mutation {arm} energy", atol=0.0, rtol=0.0)
        outcome_errors[f"{arm}_probability"] = assert_close(left["probability"], right["probability"], label=f"label mutation {arm} probability", atol=0.0, rtol=0.0)
        if left["tickets"] != right["tickets"] or not np.array_equal(left["ranks"], right["ranks"]):
            raise AssertionError(f"label/identity/metadata mutation changed {arm} predictions")
    return {"passed": True, "sample_race_id": str(sample_group.race_id.iloc[0]),
            "canonical_row_permutation": {"passed": True, "max_abs_differences": perm_errors},
            "label_identity_metadata_mutation": {"passed": True, "max_abs_differences": outcome_errors,
                                                 "model_fit_or_tau_reestimated": False}}


def write_json_new(path: Path, value: dict) -> None:
    path = confined(path, must_exist=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        import os
        os.fsync(stream.fileno())


def run_validation() -> dict:
    output_dir = HERE / "outputs/postfit_independent_validation"
    if output_dir.exists():
        raise FileExistsError(f"refusing to overwrite existing C validation outputs: {output_dir}")
    gate = verify_gate_artifacts()
    features = load_feature_table()
    fold_checks, contexts = reconstruct_fit_checks(features, gate["parameters"])

    all_races = []
    all_runners = []
    all_triples = []
    original_saved_tau_rows = []
    baseline_tickets = {}
    sample = None
    for year in YEARS:
        context = contexts[year]
        evaluation = context["evaluation"]
        groups = validate_rosters(evaluation)
        for group in groups:
            race, runners, triples, raw = race_prediction(
                group, context["scaler"], context["pair_rms"], context["beta"],
                context["baseline_tau"], context["candidate_tau"], context["saved_tau"])
            all_races.append(race)
            all_runners.extend(runners)
            all_triples.extend(triples)
            baseline_tickets[race["race_id"]] = raw["arms"]["matched_baseline"]["tickets"]
            saved = raw["arms"]["saved_original_tau"]
            g = raw["state"]["group"]
            saved_p = saved["probability"]
            t = raw["state"]["triples"]
            y = (g.finish_position.to_numpy(int) <= 3).astype(int)
            marg = saved["marginal"]
            clip = np.clip(marg, 1e-15, 1.0 - 1e-15)
            label_loss = -(y * np.log(clip) + (1 - y) * np.log(1 - clip))
            true_rank = int(saved["ranks"][raw["state"]["truth_index"]])
            original_saved_tau_rows.append({
                "race_id": race["race_id"], "race_date": race["race_date"],
                "evaluation_year": year, "distance_m": race["distance_m"],
                "true_rank": true_rank, "hit6": saved["hit6"],
                "joint_true_nll": saved["true_nll"], "full_joint_brier": saved["brier"],
                "marginal_log_loss": float(np.mean(label_loss)),
                "marginal_brier": float(np.mean(np.square(marg - y))),
                "six_mass": saved["six_mass"], "saved_tau": context["saved_tau"],
                "saved_tau_six_tickets": "|".join(saved["tickets"]),
                "baseline_six_tickets": "|".join(raw["arms"]["matched_baseline"]["tickets"]),
            })
            if sample is None and year == 2026:
                sample = group.copy()

    races = pd.DataFrame(all_races).sort_values(["race_date", "race_id"], kind="stable").reset_index(drop=True)
    runners = pd.DataFrame(all_runners).sort_values(["race_date", "race_id", "horse_number"], kind="stable").reset_index(drop=True)
    triples = pd.DataFrame(all_triples)
    saved_tau = pd.DataFrame(original_saved_tau_rows).sort_values(["race_date", "race_id"], kind="stable").reset_index(drop=True)
    if len(races) != EXPECTED_COHORT["races"] or len(runners) != EXPECTED_COHORT["runner_rows"]:
        raise AssertionError("independent evaluation cohort differs from frozen 1,779/17,412 contract")
    if races.race_date.nunique() != EXPECTED_COHORT["race_days"]:
        raise AssertionError("independent race-day count differs from frozen 269-day contract")
    if triples.groupby(["race_id", "arm"], sort=True, observed=True).size().sum() != 3 * EXPECTED_COHORT["triples"]:
        raise AssertionError("independent 3-arm triple enumeration row count mismatch")
    if len(triples) != 3 * EXPECTED_COHORT["triples"]:
        raise AssertionError("independent all-triples row count mismatch")
    q_sums = triples.groupby(["race_id", "arm"], sort=True, observed=True).probability.sum().to_numpy(float)
    if np.max(np.abs(q_sums - 1.0)) > 1e-12:
        raise AssertionError("independent full joint distributions fail normalization")
    per_race_marginal_sums = []
    marginal_columns = ["baseline_joint_marginal", "candidate_joint_marginal"]
    for _, group in runners.groupby("race_id", sort=True, observed=True):
        for column in marginal_columns:
            per_race_marginal_sums.append(float(group[column].sum()))
    if np.max(np.abs(np.asarray(per_race_marginal_sums) - 3.0)) > 1e-10:
        raise AssertionError("joint-induced runner marginals do not sum to exactly three per race")

    saved_six = compare_saved_style_six(races, baseline_tickets)
    # Require the candidate and matched arms to retain stable exact-key/rank integrity.
    chosen = triples.loc[triples.arm.isin(["matched_baseline", "candidate"])]
    rank_check = chosen.groupby(["race_id", "arm"], sort=True, observed=True).canonical_rank.agg(
        ["size", "nunique", "min", "max"])
    if (not rank_check["size"].eq(rank_check["nunique"]).all() or
            not rank_check["min"].eq(1).all() or
            not rank_check["max"].eq(rank_check["size"]).all()):
        raise AssertionError("independent canonical rank arrays are not permutations")

    old_tau = compare_original_saved_tau(saved_tau)
    if not saved_tau.saved_tau_six_tickets.equals(saved_tau.baseline_six_tickets):
        raise AssertionError("original saved tau changed additive baseline six tickets")
    invariance = invariance_checks(sample, contexts[2026]) if sample is not None else None
    if invariance is None:
        raise AssertionError("no evaluation race available for invariance checks")

    a_races = pd.read_csv(confined(A_OUT / "report/race_metrics.csv"), dtype={"race_id": "string"})
    race_cmp = compare_dataframes(races, a_races, ["race_id"], [
        "race_date", "evaluation_year", "distance_m", "runner_rows", "triple_count",
        "baseline_hit6", "candidate_hit6", "baseline_joint_true_set_nll",
        "candidate_joint_true_set_nll", "baseline_joint_brier", "candidate_joint_brier",
        "baseline_six_mass", "candidate_six_mass", "baseline_six_tickets", "candidate_six_tickets",
        "delta_hit6", "delta_joint_true_set_nll"], "A/C race metrics")
    a_runners = pd.read_csv(confined(A_OUT / "report/runner_marginals.csv"), dtype={"race_id": "string"})
    saved_runner = pd.read_parquet(confined(STYLE_OUT / "report/runner_predictions.parquet"))
    saved_runner = saved_runner.loc[saved_runner.variant.eq("F1_STYLE6"),
                                    ["api_record_id", "p_top3", "y"]].copy()
    saved_runner["api_record_id"] = pd.to_numeric(saved_runner.api_record_id, errors="raise").astype("int64")
    saved_runner = saved_runner.rename(columns={"p_top3": "saved_f1_style6_p_top3", "y": "saved_y_top3"})
    runners = runners.merge(saved_runner, on="api_record_id", how="left", validate="one_to_one")
    if runners.saved_f1_style6_p_top3.isna().any() or not np.array_equal(
            runners.y_top3.to_numpy(int), runners.saved_y_top3.to_numpy(int)):
        raise AssertionError("saved F1_STYLE6 runner probabilities/labels do not have exact key parity")
    runner_cmp = compare_dataframes(runners, a_runners, ["api_record_id"], [
        "race_id", "race_date", "evaluation_year", "horse_number", "y_top3",
        "baseline_joint_marginal", "candidate_joint_marginal",
        "saved_f1_style6_p_top3", "saved_y_top3"], "A/C runner marginals")

    a_triples = pd.read_parquet(confined(A_OUT / "report/all_triples.parquet"))
    c_two_arms = triples.loc[triples.arm.isin(["matched_baseline", "candidate"])].copy()
    triple_cmp = compare_dataframes(c_two_arms, a_triples,
        ["race_id", "arm", "triple_index"], ["race_date", "evaluation_year", "distance_m",
        "triple_numbers", "baseline_score_energy", "relationship_energy", "total_energy",
        "temperature", "probability", "is_true_set", "canonical_rank"], "A/C full triples")
    if len(a_triples) != 2 * EXPECTED_COHORT["triples"]:
        raise AssertionError("A full triple output does not contain two complete arms")

    metrics_c = independent_report_metrics(races, runners, gate["report_receipt"],
                                           gate["parameters"], gate["fit_receipt"])
    a_metrics = gate["report_metrics"]
    metric_diff = compare_nested(metrics_c, a_metrics)
    gate_result = metrics_c["primary_gate"]["research_signal_gate_passed"]
    if gate_result is not gate["report_receipt"].get("research_signal_gate_passed"):
        raise AssertionError("research-signal gate differs between independent recomputation and A receipt")
    if int(races.candidate_hit6.sum()) != int(a_metrics["primary_gate"]["candidate_hit6_total"]):
        raise AssertionError("candidate hit6 count differs from root-read A total")

    # A's output only includes the two preregistered comparison arms; C keeps the
    # saved-original-tau diagnostic separate and compares it to the frozen study.
    output_dir = HERE / "outputs/postfit_independent_validation"
    output_dir.mkdir(parents=True, exist_ok=False)
    race_path = output_dir / "independent_race_metrics.csv"
    runner_path = output_dir / "independent_runner_marginals.csv"
    triple_path = output_dir / "independent_all_triples.parquet"
    saved_tau_path = output_dir / "saved_original_tau_reference.csv"
    races.to_csv(confined(race_path, must_exist=False), index=False, encoding="utf-8")
    runners.to_csv(confined(runner_path, must_exist=False), index=False, encoding="utf-8")
    descriptor = __import__("os").open(confined(triple_path, must_exist=False),
                                      __import__("os").O_WRONLY | __import__("os").O_CREAT | __import__("os").O_EXCL,
                                      0o600)
    with __import__("os").fdopen(descriptor, "wb") as stream:
        table = pa.Table.from_pandas(triples, preserve_index=False)
        pq.write_table(table, stream, compression="zstd", use_dictionary=["race_id", "arm"])
        stream.flush()
        __import__("os").fsync(stream.fileno())
    saved_tau.to_csv(confined(saved_tau_path, must_exist=False), index=False, encoding="utf-8")

    end_hashes = {relative: digest(ROOT / relative) for relative in gate["source_hashes"]}
    if end_hashes != gate["source_hashes"]:
        raise AssertionError("locked source hashes changed during independent post-fit verification")
    receipt = {
        "passed": True,
        "mode": "independent post-fit reconstruction; no refit or temperature search",
        "study": "20261010_joint_relationship_review_v1",
        "plan_sha256": PLAN_SHA256,
        "verifier_path": (HERE / "postfit_independent_validation.py").relative_to(ROOT).as_posix(),
        "verifier_sha256": digest(HERE / "postfit_independent_validation.py"),
        "frozen_initial_c_preflight_sha256": INITIAL_C_SHA256,
        "final_c_preflight_sha256": gate["hashes"]["independent_preflight_receipt_sha256"],
        "a_source_lock_sha256": gate["hashes"]["source_lock_sha256"],
        "a_preflight_receipt_sha256": gate["hashes"]["preflight_receipt_sha256"],
        "a_fit_approval_sha256": gate["hashes"]["root_fit_approval_sha256"],
        "a_fit_parameters_sha256": gate["hashes"]["fit_parameters_sha256"],
        "a_fit_receipt_sha256": gate["hashes"]["fit_receipt_sha256"],
        "a_report_receipt_sha256": gate["hashes"]["report_receipt_sha256"],
        "a_report_metrics_sha256": digest(A_OUT / "report/report_metrics.json"),
        "a_report_race_metrics_sha256": digest(A_OUT / "report/race_metrics.csv"),
        "a_report_runner_marginals_sha256": digest(A_OUT / "report/runner_marginals.csv"),
        "a_report_all_triples_sha256": digest(A_OUT / "report/all_triples.parquet"),
        "locked_source_count": len(gate["source_hashes"]),
        "locked_sources_unchanged_before_after_validation": True,
        "evaluation_cohort": {"races": int(len(races)), "runner_rows": int(len(runners)),
                              "race_days": int(races.race_date.nunique()),
                              "all_triples_three_arms": int(len(triples)),
                              "two_primary_arm_triples": int(len(c_two_arms))},
        "fit_recomputation": {"folds": fold_checks,
                              "coefficient_optimization_reexecuted": False,
                              "temperature_optimization_reexecuted": False},
        "exact_saved_six_parity": saved_six,
        "full_distribution_invariants": {"all_three_arms_normalized_per_race": True,
                                          "runner_marginals_sum_to_three_per_race": True,
                                          "canonical_ranks_are_full_permutations": True},
        "original_saved_tau_arm_vs_frozen_probability_combo_gap": old_tau,
        "invariance_controls": invariance,
        "a_c_full_output_comparison": {"race_metrics": race_cmp,
                                       "runner_marginals": runner_cmp,
                                       "full_triple_rows": triple_cmp,
                                       "report_metrics_recursive_max_abs_diffs": metric_diff},
        "primary_gate": {"candidate_hit6_total": int(races.candidate_hit6.sum()),
                         "baseline_hit6_total": int(races.baseline_hit6.sum()),
                         "delta_hit6_mean": float(races.delta_hit6.mean()),
                         "delta_hit6_ci95": metrics_c["primary_gate"]["delta_hit6_date_bootstrap_95ci"],
                         "candidate_joint_true_set_nll_mean": float(races.candidate_joint_true_set_nll.mean()),
                         "baseline_joint_true_set_nll_mean": float(races.baseline_joint_true_set_nll.mean()),
                         "delta_joint_true_set_nll_mean": float(races.delta_joint_true_set_nll.mean()),
                         "delta_joint_true_set_nll_ci95": metrics_c["primary_gate"]["delta_joint_true_set_nll_date_bootstrap_95ci"],
                         "research_signal_gate_passed": bool(gate_result)},
        "c_artifacts": {
            "independent_race_metrics_sha256": digest(race_path),
            "independent_runner_marginals_sha256": digest(runner_path),
            "independent_all_triples_sha256": digest(triple_path),
            "saved_original_tau_reference_sha256": digest(saved_tau_path),
        },
        "new_candidate_model_or_hyperparameter_search": False,
        "central_publication_or_operational_change": False,
    }
    write_json_new(output_dir / "independent_postfit_validation.json", receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-after-root-approval", action="store_true",
                        help="explicitly run the authorized post-fit metric reconstruction")
    args = parser.parse_args()
    if not args.execute_after_root_approval:
        print("Prepared only. Post-fit outcome reconstruction requires the explicit root-approved execution flag.")
        return 0
    receipt = run_validation()
    print(json.dumps(receipt, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
