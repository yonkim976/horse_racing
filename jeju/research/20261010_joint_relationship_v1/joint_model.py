"""Shared, fixed-contract utilities for the F1_STYLE6 relationship study."""
from __future__ import annotations

from itertools import combinations
import hashlib
import json
import math
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from scipy.optimize import minimize, minimize_scalar
from scipy.special import logsumexp


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
STYLE = HERE.parent / "20261010_style_history_ablation_v1"
STYLE_OUT = STYLE / "outputs"
OUT = HERE / "outputs"
C_FINAL_RECEIPT_PATH = HERE.parent / "20261010_joint_relationship_review_v1" / "outputs" / "independent_preflight_final.json"
FEATURES_PATH = STYLE_OUT / "features.parquet"
BASELINE_SIX_PATH = STYLE_OUT / "report" / "canonical_six_combinations.csv"
BASELINE_RUNNER_PATH = STYLE_OUT / "f1_reproduced_runner_predictions.parquet"
SAVED_STYLE_RUNNER_PATH = STYLE_OUT / "report" / "runner_predictions.parquet"
LINEAGE_PATH = STYLE_OUT / "style_history_lineage.parquet"
STYLE_MANIFEST_PATH = STYLE / "ARTIFACT_MANIFEST.json"
STYLE_PREPARED_LOCK_PATH = STYLE_OUT / "prepared_lock.json"
GAP = HERE.parent / "20261010_probability_combo_gap_v1"
GAP_SOURCE_LOCK_PATH = GAP / "outputs" / "source_lock.json"
GAP_CONTRACT_PATH = GAP / "data_contract.json"
GAP_MANIFEST_PATH = GAP / "ARTIFACT_MANIFEST.json"
GAP_MANIFEST_SHA256 = "59560a8b5c3d808e584314fdc2210c66be24495de87de0d2b3cce67e6f419076"

YEARS = (2024, 2025, 2026)
STYLE_FEATURES = (
    "hist_s1f_relpos_mean5",
    "hist_s1f_relpos_n",
    "hist_s1f_to_c4_forward_mean5",
    "hist_s1f_to_c4_pair_n",
    "hist_c4_to_g1f_forward_mean5",
    "hist_c4_to_g1f_pair_n",
)
INPUT_COLUMNS = ("score",) + STYLE_FEATURES
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

EXPECTED_PLAN_SHA256 = "e0a34c6962112d88bfec7e645efbd8e4ea69bf4aada088f580e1188bac1207f3"
EXPECTED_COHORT = {"races": 1779, "runner_rows": 17412, "race_days": 269}
REGULARIZATION_LAMBDA = 1.0
DEGENERATE_TOL = 1e-12
PROJECTION_TOL = 1e-10
TEMP_BOUNDS = (0.35, 4.0)
OPTIMIZER_OPTIONS = {"maxiter": 500, "ftol": 1e-12, "gtol": 1e-8}
TEMP_XATOL = 1e-12
BOOTSTRAP_DRAWS = 2000
BOOTSTRAP_SEED = 20261008


def confined(path: Path, *, must_exist: bool = True) -> Path:
    """Resolve only fixed project paths and reject anything outside the repo."""
    resolved = Path(path).resolve(strict=must_exist)
    try:
        resolved.relative_to(ROOT)
    except ValueError as exc:
        raise ValueError(f"path escapes repository root: {path}") from exc
    return resolved


def sha256(path: Path) -> str:
    path = confined(path)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_record(path: Path) -> dict:
    path = confined(path)
    return {"sha256": sha256(path), "bytes": path.stat().st_size}


def load_json(path: Path) -> dict:
    path = confined(path)
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def write_json_new(path: Path, payload: dict) -> None:
    """Create a JSON artifact exactly once; never overwrite prior work."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    resolved_parent = confined(path.parent)
    target = resolved_parent / path.name
    with target.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        import os
        os.fsync(stream.fileno())


def input_paths() -> list[Path]:
    paths = [
        HERE / "PLAN.md",
        HERE / "SOURCE_AVAILABILITY.md",
        HERE / "joint_model.py",
        HERE / "preflight.py",
        HERE / "fit.py",
        HERE / "report.py",
        HERE / "finalize_report.py",
        HERE / "verify.py",
        HERE / "accept_c_preflight.py",
        STYLE_MANIFEST_PATH,
        STYLE_PREPARED_LOCK_PATH,
        FEATURES_PATH,
        BASELINE_SIX_PATH,
        BASELINE_RUNNER_PATH,
        SAVED_STYLE_RUNNER_PATH,
        LINEAGE_PATH,
        GAP_SOURCE_LOCK_PATH,
        GAP_CONTRACT_PATH,
        GAP_MANIFEST_PATH,
        ROOT / "jeju" / "AGENTS.md",
        ROOT / "jeju" / "docs" / "RESTART_PLAN_20260928.md",
        ROOT / "jeju" / "review_documents" / "README.md",
        ROOT / "jeju" / "research" / "RESEARCH_PUBLICATION_POLICY.md",
        ROOT / "jeju" / "data" / "jeju_native_core.sqlite3",
        ROOT / "config" / "prediction_model_registry.json",
        ROOT / "jeju" / "models" / "current" / "metadata.json",
        ROOT / "jeju" / "models" / "current" / "HY_R_FORM.pkl",
    ]
    for year in YEARS:
        folder = STYLE_OUT / f"F1_STYLE6_{year}"
        paths.extend((folder / "meta.json", folder / "top3.txt",
                      folder / "calibration_scores.parquet", folder / "evaluation_scores.parquet"))
    return paths


def expected_manifest_references() -> dict[str, list[dict[str, str]]]:
    style_manifest = load_json(STYLE_MANIFEST_PATH)
    style_refs = style_manifest["study_artifacts"]
    expected: dict[str, list[dict[str, str]]] = {}

    def add(path: Path, digest: str, reference: str) -> None:
        key = path.relative_to(ROOT).as_posix()
        expected.setdefault(key, []).append({"sha256": str(digest), "reference": reference})

    for path in input_paths():
        relative = path.relative_to(ROOT).as_posix()
        if relative in style_refs:
            add(path, style_refs[relative]["sha256"], f"{STYLE_MANIFEST_PATH.relative_to(ROOT)}:study_artifacts/{relative}")
        protected = style_manifest.get("protected_sources", {}).get(relative)
        if isinstance(protected, dict) and "sha256" in protected:
            add(path, protected["sha256"], f"{STYLE_MANIFEST_PATH.relative_to(ROOT)}:protected_sources/{relative}")

    prepared = load_json(STYLE_PREPARED_LOCK_PATH)
    for name, digest in prepared.get("artifacts", {}).items():
        path = STYLE_OUT / name
        if path in input_paths():
            add(path, digest, f"{STYLE_PREPARED_LOCK_PATH.relative_to(ROOT)}:artifacts/{name}")
    for relative, digest in prepared.get("protected", {}).items():
        path = ROOT / relative
        if path in input_paths():
            add(path, digest["sha256"], f"{STYLE_PREPARED_LOCK_PATH.relative_to(ROOT)}:protected/{relative}")

    for year in YEARS:
        meta_path = STYLE_OUT / f"F1_STYLE6_{year}" / "meta.json"
        model_path = STYLE_OUT / f"F1_STYLE6_{year}" / "top3.txt"
        add(model_path, load_json(meta_path)["model_sha256"],
            f"{meta_path.relative_to(ROOT)}:model_sha256")

    add(GAP_SOURCE_LOCK_PATH,
        "e66b4f33919af721a3ebceccfef2966783aea0b4b322d760de179ef06fa921a9",
        "SOURCE_AVAILABILITY.md:declared probability_combo_gap_v1 source-lock SHA-256")

    # The combo-gap manifest stores paths relative to its own folder; the source
    # lock stores repository-relative keys. Preserve both declarations exactly.
    gap_lock = load_json(GAP_SOURCE_LOCK_PATH)
    add(STYLE_MANIFEST_PATH, gap_lock["artifact_manifest_sha256"],
        f"{GAP_SOURCE_LOCK_PATH.relative_to(ROOT)}:artifact_manifest_sha256")
    add(GAP_MANIFEST_PATH, GAP_MANIFEST_SHA256,
        "root-reviewed frozen hash for probability_combo_gap_v1/ARTIFACT_MANIFEST.json")
    add(GAP_CONTRACT_PATH, gap_lock["data_contract_sha256"],
        f"{GAP_SOURCE_LOCK_PATH.relative_to(ROOT)}:data_contract_sha256")
    add(STYLE_PREPARED_LOCK_PATH, gap_lock["prepared_lock_sha256"],
        f"{GAP_SOURCE_LOCK_PATH.relative_to(ROOT)}:prepared_lock_sha256")
    for relative, record in gap_lock.get("source_files", {}).items():
        path = ROOT / relative
        if path in input_paths():
            add(path, record["sha256"], f"{GAP_SOURCE_LOCK_PATH.relative_to(ROOT)}:source_files/{relative}")
    combo_manifest_path = GAP_MANIFEST_PATH
    if combo_manifest_path.is_file():
        combo_manifest = load_json(combo_manifest_path)
        for relative, entry in combo_manifest.get("files", {}).items():
            path = GAP / relative
            if path in input_paths():
                digest = entry["sha256"] if isinstance(entry, dict) else entry
                add(path, digest, f"{combo_manifest_path.relative_to(ROOT)}:files/{relative}")
    return expected


def expected_manifest_hashes() -> dict[str, str]:
    references = expected_manifest_references()
    expected = {}
    for path, declarations in references.items():
        hashes = {item["sha256"] for item in declarations}
        if len(hashes) != 1:
            raise AssertionError(f"frozen source declarations disagree for {path}: {declarations}")
        expected[path] = next(iter(hashes))
    return expected


def lock_sources() -> dict[str, dict]:
    expected = expected_manifest_hashes()
    references = expected_manifest_references()
    locked = {}
    for path in input_paths():
        record = file_record(path)
        relative = path.relative_to(ROOT).as_posix()
        if relative in expected and record["sha256"] != expected[relative]:
            raise AssertionError(f"source differs from frozen manifest: {relative}")
        declarations = references.get(relative, [])
        locked[relative] = record
        locked[relative]["expected_sha256"] = expected.get(relative)
        locked[relative]["verified_references"] = declarations
    return locked


def current_source_hashes() -> dict[str, str]:
    return {name: record["sha256"] for name, record in lock_sources().items()}


def read_scores(path: Path) -> pd.DataFrame:
    path = confined(path)
    frame = pd.read_parquet(path)
    if list(frame.columns) != ["api_record_id", "score"]:
        raise AssertionError(f"unexpected score schema: {path}")
    if frame.api_record_id.isna().any() or frame.api_record_id.duplicated().any():
        raise AssertionError(f"score IDs are missing or duplicated: {path}")
    frame["api_record_id"] = frame.api_record_id.astype("int64")
    frame["score"] = pd.to_numeric(frame.score, errors="raise").astype("float64")
    if not np.isfinite(frame.score.to_numpy()).all():
        raise AssertionError(f"non-finite score: {path}")
    return frame


def join_scores(features: pd.DataFrame, score_path: Path, year: int,
                expected_rows: int, *, role: str) -> pd.DataFrame:
    year_rows = features.loc[features.year.eq(year)].copy()
    scores = read_scores(score_path)
    if len(year_rows) != expected_rows or len(scores) != expected_rows:
        raise AssertionError(f"{role} row count mismatch for {year}")
    if set(year_rows.api_record_id.astype("int64")) != set(scores.api_record_id):
        raise AssertionError(f"{role} score IDs do not exactly cover feature rows for {year}")
    score_map = scores.set_index("api_record_id").score
    year_rows["api_record_id"] = year_rows.api_record_id.astype("int64")
    year_rows["score"] = year_rows.api_record_id.map(score_map)
    if year_rows.score.isna().any():
        raise AssertionError(f"{role} score join produced missing values for {year}")
    year_rows["score"] = year_rows.score.astype("float64")
    year_rows["race_date"] = pd.to_datetime(year_rows.race_date, errors="raise").dt.normalize()
    return year_rows.sort_values(["race_id", "horse_number"], kind="stable").reset_index(drop=True)


def assert_runner_features(frame: pd.DataFrame) -> None:
    required = {
        "api_record_id", "race_id", "race_date", "year", "horse_id", "horse_number",
        "field_n", "finish_position", "score", *STYLE_FEATURES,
    }
    missing = required.difference(frame.columns)
    if missing:
        raise AssertionError(f"missing required columns: {sorted(missing)}")
    if frame.api_record_id.isna().any() or frame.api_record_id.duplicated().any():
        raise AssertionError("runner api_record_id must be unique within fold data")
    if frame.race_id.isna().any() or frame.horse_id.isna().any():
        raise AssertionError("runner or race ID missing")
    if not np.isfinite(frame.score.to_numpy(float)).all():
        raise AssertionError("non-finite raw score")
    for mean_name, count_name in COUNT_FOR_MEAN.items():
        count = pd.to_numeric(frame[count_name], errors="raise").to_numpy(float)
        mean = pd.to_numeric(frame[mean_name], errors="coerce").to_numpy(float)
        if not np.isfinite(count).all() or not np.equal(count, np.floor(count)).all():
            raise AssertionError(f"invalid history support count: {count_name}")
        if (count < 0).any() or (count > 5).any():
            raise AssertionError(f"history support count outside 0..5: {count_name}")
        valid = count > 0
        if not np.array_equal(np.isfinite(mean), valid):
            raise AssertionError(f"mean/count missingness mismatch: {mean_name}")


def race_groups(frame: pd.DataFrame) -> list[pd.DataFrame]:
    groups = []
    for race_id, group in frame.groupby("race_id", sort=True, observed=True):
        group = group.sort_values("horse_number", kind="stable").reset_index(drop=True)
        n = len(group)
        if n < 5 or math.comb(n, 3) < 6:
            raise AssertionError(f"unsupported field size in {race_id}: N={n}")
        if group.horse_id.nunique() != n or group.horse_number.nunique() != n:
            raise AssertionError(f"duplicate runner identity or number in {race_id}")
        field_n = pd.to_numeric(group.field_n, errors="raise").to_numpy(int)
        if not np.equal(field_n, n).all():
            raise AssertionError(f"field_n does not match complete roster in {race_id}")
        if group.race_date.nunique() != 1:
            raise AssertionError(f"multiple race dates in {race_id}")
        finish = pd.to_numeric(group.finish_position, errors="coerce").to_numpy(float)
        expected_ranks = np.arange(1, n + 1, dtype=np.float64)
        if (not np.isfinite(finish).all() or
                not np.array_equal(np.sort(finish), expected_ranks)):
            raise AssertionError(
                f"race finish positions are not a unique complete 1..N permutation: "
                f"{race_id}; finish={finish.tolist()}"
            )
        truth = np.flatnonzero(finish <= 3)
        if len(truth) != 3 or not np.array_equal(np.sort(finish[truth]), np.array([1., 2., 3.])):
            raise AssertionError(f"race does not have exact 1,2,3 top3 labels: {race_id}")
        groups.append(group)
    if not groups:
        raise AssertionError("empty race set")
    return groups


def split_calibration(calibration: pd.DataFrame, evaluation: pd.DataFrame, meta: dict) -> dict:
    dates = pd.to_datetime(calibration.race_date, errors="raise").dt.normalize()
    evaluation_dates = pd.to_datetime(evaluation.race_date, errors="raise").dt.normalize()
    if calibration.empty or evaluation.empty:
        raise AssertionError("calibration/evaluation frame is empty")
    calibration_min, calibration_max = dates.min(), dates.max()
    evaluation_min, evaluation_max = evaluation_dates.min(), evaluation_dates.max()
    metadata_dates = {
        "calibration_min": calibration_min,
        "calibration_max": calibration_max,
        "evaluation_min": evaluation_min,
        "evaluation_max": evaluation_max,
    }
    for name, actual in metadata_dates.items():
        declared = pd.to_datetime(meta[name], errors="raise").normalize()
        if actual != declared:
            raise AssertionError(f"actual {name} {actual.date()} differs from metadata {declared.date()}")
    h1_mask = dates.dt.month.le(6)
    h2_mask = dates.dt.month.ge(7)
    if not h1_mask.any() or not h2_mask.any():
        raise AssertionError("calendar H1/H2 split is empty")
    h2_dates = dates.loc[h2_mask]
    first_h2 = h2_dates.min()
    h1_cutoff = first_h2 - pd.Timedelta(days=2)
    fit_mask = h1_mask & dates.le(h1_cutoff)
    purge_mask = h1_mask & dates.gt(h1_cutoff)
    h1 = calibration.loc[fit_mask].copy()
    h2 = calibration.loc[h2_mask].copy()
    if h1.empty or h2.empty:
        raise AssertionError("H1 fit or H2 calibration is empty after T-2 purge")
    h1_dates = pd.to_datetime(h1.race_date).dt.normalize()
    h2_dates = pd.to_datetime(h2.race_date).dt.normalize()
    if h1_dates.max() > h2_dates.min() - pd.Timedelta(days=2):
        raise AssertionError("H1 label date violates H2 T-2 boundary")
    if h2_dates.max() > evaluation_min - pd.Timedelta(days=2):
        raise AssertionError("H2 label date violates evaluation T-2 boundary")
    refit_max = pd.to_datetime(meta["refit_max"], errors="raise").normalize()
    if refit_max > h1_dates.min() - pd.Timedelta(days=2):
        raise AssertionError("base-model refit_max violates H1 T-2 boundary")
    return {
        "h1": h1.reset_index(drop=True),
        "h2": h2.reset_index(drop=True),
        "purged": calibration.loc[purge_mask].copy().reset_index(drop=True),
        "h1_cutoff": h1_cutoff,
        "first_h2": first_h2,
        "h1_max": h1_dates.max(),
        "h2_max": h2_dates.max(),
        "calibration_min": calibration_min,
        "calibration_max": calibration_max,
        "evaluation_min": evaluation_min,
        "evaluation_max": evaluation_max,
        "refit_max": refit_max,
        "pre_purge_h1_races": int(calibration.loc[h1_mask, "race_id"].nunique()),
        "h1_races": int(h1.race_id.nunique()),
        "h2_races": int(h2.race_id.nunique()),
        "purged_races": int(calibration.loc[purge_mask, "race_id"].nunique()),
        "h1_days": int(h1.race_date.nunique()),
        "h2_days": int(h2.race_date.nunique()),
    }


def fit_runner_scaler(frame: pd.DataFrame) -> dict:
    stats = {}
    field_n = pd.to_numeric(frame.field_n, errors="raise").to_numpy(float)
    weights = 1.0 / field_n
    for name in INPUT_COLUMNS:
        values = pd.to_numeric(frame[name], errors="coerce").to_numpy(float)
        if name in MEAN_COLUMNS:
            count_name = COUNT_FOR_MEAN[name]
            count = pd.to_numeric(frame[count_name], errors="raise").to_numpy(float)
            valid = (count > 0) & np.isfinite(values)
        else:
            valid = np.isfinite(values)
        denominator = float(weights[valid].sum())
        if denominator <= 0:
            stats[name] = {"mean": 0.0, "sd": 0.0, "valid_weight_sum": denominator,
                           "valid_rows": int(valid.sum()), "degenerate": True}
            continue
        mean = float(np.sum(weights[valid] * values[valid]) / denominator)
        variance = float(np.sum(weights[valid] * np.square(values[valid] - mean)) / denominator)
        sd = math.sqrt(max(variance, 0.0))
        degenerate = sd <= DEGENERATE_TOL
        stats[name] = {
            "mean": mean,
            "sd": 0.0 if degenerate else sd,
            "valid_weight_sum": denominator,
            "valid_rows": int(valid.sum()),
            "degenerate": bool(degenerate),
        }
    return stats


def transform_runner(frame: pd.DataFrame, scaler: dict) -> tuple[np.ndarray, np.ndarray]:
    n = len(frame)
    values = np.zeros((n, len(INPUT_COLUMNS)), dtype=np.float64)
    valid = np.ones((n, len(INPUT_COLUMNS)), dtype=bool)
    for column, name in enumerate(INPUT_COLUMNS):
        raw = pd.to_numeric(frame[name], errors="coerce").to_numpy(float)
        if name in MEAN_COLUMNS:
            count = pd.to_numeric(frame[COUNT_FOR_MEAN[name]], errors="raise").to_numpy(float)
            valid[:, column] = (count > 0) & np.isfinite(raw)
        else:
            valid[:, column] = np.isfinite(raw)
        stat = scaler[name]
        if stat["degenerate"]:
            continue
        values[valid[:, column], column] = (
            raw[valid[:, column]] - float(stat["mean"])
        ) / float(stat["sd"])
    if not np.isfinite(values).all():
        raise AssertionError("non-finite normalized runner feature")
    return values, valid


def pair_indices(n: int) -> np.ndarray:
    return np.asarray(list(combinations(range(n), 2)), dtype=np.int64)


def triple_indices(n: int) -> np.ndarray:
    return np.asarray(list(combinations(range(n), 3)), dtype=np.int64)


def pair_basis(runner_values: np.ndarray, runner_valid: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    n = runner_values.shape[0]
    pairs = pair_indices(n)
    left, right = pairs[:, 0], pairs[:, 1]
    columns = [runner_values[left, 0] * runner_values[right, 0]]
    for k in range(len(INPUT_COLUMNS)):
        difference = np.abs(runner_values[left, k] - runner_values[right, k])
        if INPUT_COLUMNS[k] in MEAN_COLUMNS:
            difference[~(runner_valid[left, k] & runner_valid[right, k])] = 0.0
        columns.append(difference)
    for name in MEAN_COLUMNS:
        k = INPUT_COLUMNS.index(name)
        columns.append((~(runner_valid[left, k] & runner_valid[right, k])).astype(np.float64))
    matrix = np.column_stack(columns).astype(np.float64, copy=False)
    if matrix.shape[1] != len(PAIR_FEATURES) or not np.isfinite(matrix).all():
        raise AssertionError("invalid pair basis")
    return pairs, matrix


def project_pair_basis(pair_ids: np.ndarray, phi: np.ndarray, n: int) -> tuple[np.ndarray, np.ndarray]:
    if n < 3 or len(pair_ids) != math.comb(n, 2):
        raise AssertionError("pair graph is incomplete")
    left, right = pair_ids[:, 0], pair_ids[:, 1]
    degree = np.zeros((n, phi.shape[1]), dtype=np.float64)
    for row, (i, j) in enumerate(pair_ids):
        degree[i] += phi[row]
        degree[j] += phi[row]
    total = phi.sum(axis=0)
    unary = (degree - total / (n - 1)) / (n - 2)
    residual = phi - unary[left] - unary[right]
    row_sum = np.zeros_like(degree)
    for row, (i, j) in enumerate(pair_ids):
        row_sum[i] += residual[row]
        row_sum[j] += residual[row]
    if np.max(np.abs(row_sum)) > PROJECTION_TOL:
        raise AssertionError("pair projection failed zero row-sum check")
    return residual, unary


def clean_degenerate_residual(residual: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    cleaned = residual.copy()
    preclean_max = np.max(np.abs(cleaned), axis=0) if len(cleaned) else np.zeros(cleaned.shape[1])
    zeroed = preclean_max <= DEGENERATE_TOL
    cleaned[:, zeroed] = 0.0
    return cleaned, preclean_max


def triple_pair_rows(pair_ids: np.ndarray, triples: np.ndarray) -> np.ndarray:
    lookup = {tuple(pair): row for row, pair in enumerate(pair_ids.tolist())}
    rows = np.empty((len(triples), 3), dtype=np.int64)
    for row, (i, j, k) in enumerate(triples):
        rows[row, 0] = lookup[(int(i), int(j))]
        rows[row, 1] = lookup[(int(i), int(k))]
        rows[row, 2] = lookup[(int(j), int(k))]
    return rows


def triple_relation_features(pair_ids: np.ndarray, residual: np.ndarray,
                             triples: np.ndarray) -> np.ndarray:
    pair_rows = triple_pair_rows(pair_ids, triples)
    return residual[pair_rows[:, 0]] + residual[pair_rows[:, 1]] + residual[pair_rows[:, 2]]


def baseline_energies(scores: np.ndarray, triples: np.ndarray) -> np.ndarray:
    # Match the saved F1 evaluator: sort each triple's raw scores, then np.sum(axis=1).
    return np.sort(scores[triples], axis=1).sum(axis=1)


def stable_top_indices(energies: np.ndarray, k: int = 6) -> np.ndarray:
    return np.argsort(-energies, kind="stable")[:k]


def top_ticket_numbers(group: pd.DataFrame, triples: np.ndarray,
                       order: np.ndarray) -> list[str]:
    numbers = group.horse_number.to_numpy(int)
    return [",".join(str(int(x)) for x in sorted(numbers[triples[idx]])) for idx in order]


def exact_set_objective(beta: np.ndarray, race_data: list[dict], lam: float = REGULARIZATION_LAMBDA):
    total_loss = 0.0
    gradient = np.zeros_like(beta, dtype=np.float64)
    for race in race_data:
        x = race["triple_features"]
        energy = race["baseline_energy"] + x @ beta
        log_z = float(logsumexp(energy))
        probability = np.exp(energy - log_z)
        truth_index = int(race["truth_index"])
        total_loss += log_z - float(energy[truth_index])
        gradient += probability @ x - x[truth_index]
    n_races = len(race_data)
    if n_races < 1:
        raise ValueError("empty conditional-likelihood training set")
    total_loss /= n_races
    gradient /= n_races
    loss = total_loss + 0.5 * lam * float(beta @ beta)
    gradient += lam * beta
    return loss, gradient


def fit_beta(race_data: list[dict]) -> dict:
    if not race_data:
        raise ValueError("empty H1 conditional-likelihood training set")
    active = np.asarray(race_data[0]["active_columns"], dtype=np.int64)
    if len(active) == 0:
        zero_beta = np.zeros(len(PAIR_FEATURES), dtype=np.float64)
        baseline_objective, _ = exact_set_objective(zero_beta, race_data, REGULARIZATION_LAMBDA)
        return {"beta": zero_beta.tolist(), "active_columns": [], "success": True,
                "message": "all pair residual columns are degenerate", "iterations": 0,
                "objective": float(baseline_objective), "gradient_inf_norm": None,
                "optimizer_skipped": True}
    reduced = []
    for race in race_data:
        reduced.append({**race, "triple_features": race["triple_features"][:, active]})
    initial = np.zeros(len(active), dtype=np.float64)
    result = minimize(
        exact_set_objective,
        initial,
        args=(reduced, REGULARIZATION_LAMBDA),
        method="L-BFGS-B",
        jac=True,
        options=OPTIMIZER_OPTIONS,
    )
    if not result.success or not np.isfinite(result.x).all():
        raise RuntimeError(f"relationship coefficient fit failed: {result.message}")
    full_beta = np.zeros(len(PAIR_FEATURES), dtype=np.float64)
    full_beta[active] = result.x
    return {"beta": full_beta.tolist(), "active_columns": active.tolist(),
            "success": bool(result.success), "message": str(result.message),
            "iterations": int(result.nit), "objective": float(result.fun),
            "gradient_inf_norm": float(np.max(np.abs(result.jac))),
            "optimizer_skipped": False}


def set_nll(energies: np.ndarray, truth_index: int, tau: float) -> float:
    scaled = energies / float(tau)
    return float(logsumexp(scaled) - scaled[int(truth_index)])


def fit_temperature(races: list[dict], energy_key: str) -> dict:
    def objective(tau: float) -> float:
        return float(np.mean([
            set_nll(race[energy_key], race["truth_index"], tau) for race in races
        ]))
    result = minimize_scalar(
        objective,
        bounds=TEMP_BOUNDS,
        method="bounded",
        options={"xatol": TEMP_XATOL},
    )
    if not result.success or not math.isfinite(float(result.x)):
        raise RuntimeError(f"temperature calibration failed: {result.message}")
    return {"tau": float(result.x), "h2_nll": float(result.fun),
            "success": bool(result.success), "message": str(result.message),
            "bounds": list(TEMP_BOUNDS), "xatol": TEMP_XATOL}


def probability_distribution(energies: np.ndarray, tau: float) -> np.ndarray:
    scaled = energies / float(tau)
    return np.exp(scaled - logsumexp(scaled))


def six_mass_reliability_bin(value: float) -> int:
    return min(int(math.floor(float(value) * 10.0)), 9)


def paired_date_bootstrap(frame: pd.DataFrame, delta_column: str,
                          draws: int = BOOTSTRAP_DRAWS,
                          seed: int = BOOTSTRAP_SEED,
                          expected_days: int | None = None) -> dict:
    daily = frame.groupby("race_date", as_index=False, observed=True)[delta_column].agg(
        total="sum", races="size")
    if expected_days is not None and len(daily) != expected_days:
        raise AssertionError("unexpected race-day count for paired date bootstrap")
    rng = np.random.default_rng(seed)
    totals = daily.total.to_numpy(float)
    counts = daily.races.to_numpy(float)
    indices = rng.integers(0, len(daily), size=(draws, len(daily)))
    values = totals[indices].sum(axis=1) / counts[indices].sum(axis=1)
    return {
        "estimate": float(frame[delta_column].mean()),
        "ci95_low": float(np.quantile(values, 0.025)),
        "ci95_high": float(np.quantile(values, 0.975)),
        "draws": draws,
        "seed": seed,
        "cluster": "race_date",
    }


def synthetic_projection_control(seed: int = 20261010) -> dict:
    rng = np.random.default_rng(seed)
    checks = []
    for n in (5, 7, 10):
        pairs = pair_indices(n)
        triples = triple_indices(n)
        unary = rng.normal(size=(n, 3))
        constant = rng.normal(size=(1, 3))
        phi = unary[pairs[:, 0]] + unary[pairs[:, 1]] + constant
        residual, _ = project_pair_basis(pairs, phi, n)
        cleaned, preclean = clean_degenerate_residual(residual)
        triple_features = triple_relation_features(pairs, cleaned, triples)
        incidence = np.zeros((len(triples), n), dtype=np.float64)
        incidence[np.arange(len(triples))[:, None], triples] = 1.0
        orthogonality = incidence.T @ triple_features
        scores = rng.normal(size=n)
        base = baseline_energies(scores, triples)
        candidate = base + triple_features @ np.asarray([0.2, -0.1, 0.3])
        control_top = stable_top_indices(base)
        candidate_top = stable_top_indices(candidate)
        base_probability = probability_distribution(base, 1.25)
        candidate_probability = probability_distribution(candidate, 1.25)
        checks.append({
            "field_n": n,
            "preclean_max_abs": float(np.max(preclean)),
            "cleaned_max_abs": float(np.max(np.abs(cleaned))),
            "A_transpose_G_max_abs": float(np.max(np.abs(orthogonality))),
            "energy_equal_after_clean": bool(np.array_equal(base, candidate)),
            "top6_equal_after_clean": bool(np.array_equal(control_top, candidate_top)),
            "probability_equal_after_clean": bool(np.array_equal(base_probability, candidate_probability)),
        })
    if any(item["preclean_max_abs"] > DEGENERATE_TOL for item in checks):
        raise AssertionError("synthetic unary-only projection exceeds degeneracy tolerance")
    if any(item["cleaned_max_abs"] != 0.0 or item["A_transpose_G_max_abs"] > PROJECTION_TOL or
           not item["energy_equal_after_clean"] or not item["top6_equal_after_clean"] or
           not item["probability_equal_after_clean"]
           for item in checks):
        raise AssertionError("synthetic unary-only negative control failed")
    return {"passed": True, "seed": seed, "checks": checks,
            "degenerate_tolerance": DEGENERATE_TOL,
            "projection_tolerance": PROJECTION_TOL}
