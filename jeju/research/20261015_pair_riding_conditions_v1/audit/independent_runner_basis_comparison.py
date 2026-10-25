"""Compare the final builder runner basis with the independently recalculated rows."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
STUDY = HERE.parent
ROOT = STUDY.parents[2]
BUILDER_RUNNERS = STUDY / "outputs_prefit_v2/riding_conditions_runner_basis.parquet"
BUILDER_EVENT_CACHE = STUDY / "outputs/source_started_event_rider.parquet"
BUILDER_PREFLIGHT = STUDY / "outputs_prefit_v2/FEATURE_PREFLIGHT.json"
BUILDER_CACHE_RECEIPT = STUDY / "outputs/SOURCE_CACHE_RECEIPT.json"
SOURCE_LOCK = STUDY / "SOURCE_HASHES.json"
PREPARE_CODE = STUDY / "prepare.py"
BASIS_CODE = STUDY / "riding_conditions_basis.py"
INDEPENDENT_RUNNERS = HERE / "independent_runner_features.parquet"
INDEPENDENT_RECEIPT = HERE / "independent_prefit_receipt.json"
H1_DUPLICATE_RECEIPT = HERE / "independent_h1_duplicate_receipt.json"
OUTPUT = HERE / "independent_runner_basis_comparison_receipt.json"
ABS_TOL = 1e-12


class AuditError(RuntimeError):
    pass


def require(ok: bool, message: str) -> None:
    if not ok:
        raise AuditError(message)


def checked(path: Path) -> Path:
    require(not path.is_symlink(), f"symlink input is not allowed: {path}")
    resolved = path.resolve(strict=True)
    require(resolved.is_relative_to(ROOT) and resolved.is_file(), f"input outside workspace: {path}")
    return resolved


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with checked(path).open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def compare_numeric(name: str, left: pd.Series, right: pd.Series) -> dict[str, Any]:
    a = pd.to_numeric(left, errors="coerce").to_numpy(dtype=float)
    b = pd.to_numeric(right, errors="coerce").to_numpy(dtype=float)
    same_na = np.isnan(a) & np.isnan(b)
    close = np.isclose(a, b, rtol=0.0, atol=ABS_TOL, equal_nan=True)
    mismatch = ~close
    finite_delta = np.abs(a[~same_na] - b[~same_na])
    return {
        "mismatch_rows": int(mismatch.sum()),
        "max_absolute_difference": float(finite_delta.max()) if len(finite_delta) else 0.0,
        "tolerance": {"rtol": 0.0, "atol": ABS_TOL, "equal_nan": True},
    }


def normalized_text(series: pd.Series) -> pd.Series:
    result = series.astype("string").str.strip()
    return result.fillna("")


def compare_text(name: str, left: pd.Series, right: pd.Series) -> dict[str, int]:
    a, b = normalized_text(left), normalized_text(right)
    mismatch = a.ne(b)
    return {"mismatch_rows": int(mismatch.sum())}


def main() -> None:
    require(not OUTPUT.exists(), "refusing to overwrite runner basis comparison receipt")
    builder = pd.read_parquet(checked(BUILDER_RUNNERS))
    independent = pd.read_parquet(checked(INDEPENDENT_RUNNERS))
    cache = pd.read_parquet(checked(BUILDER_EVENT_CACHE), columns=["api_record_id", "event_jockey_id"])
    for name, frame in (("builder", builder), ("independent", independent), ("event_cache", cache)):
        require("api_record_id" in frame, f"{name} lacks runner key")
        frame["api_record_id"] = pd.to_numeric(frame["api_record_id"], errors="raise").astype("int64")
        require(frame["api_record_id"].is_unique, f"{name} runner key is duplicate")

    key_columns = ["api_record_id", "race_id", "race_date", "year", "horse_id", "horse_number"]
    require(set(key_columns + ["distance_m", "tminus2_cutoff"]).issubset(builder.columns),
            "builder runner basis key columns changed")
    require(set(["race_id", "race_date", "horse_id", "horse_number", "history_cutoff",
                 "current_jockey_id", "previous_started_api_record_id_asof_t2", "previous_started_date_asof_t2",
                 "previous_rider_retained", "previous_rider_unknown", "rider365_delta_feature_value",
                 "rider365_delta_unavailable", "rider365_current_n", "rider365_previous_n",
                 "rider365_current_R", "horse_past_started_n_asof_t2",
                 "horse_current_rider_past_started_n", "horse_current_rider_recency_days_asof_t2",
                 "horse_current_rider_first_observed", "horse_current_rider_history_unavailable"]).issubset(independent.columns),
            "independent runner audit schema changed")
    require(len(builder) == len(independent) == 42_690, "builder/independent runner row count changed")

    merged = builder.merge(independent, on="api_record_id", how="outer", suffixes=("_builder", "_independent"),
                           validate="one_to_one", indicator=True)
    require(merged["_merge"].eq("both").all(), "builder/independent runner API-key coverage differs")
    key_comparisons: dict[str, dict[str, int]] = {}
    for column in ("race_id", "race_date", "horse_id"):
        left = merged[f"{column}_builder"]
        right = merged[f"{column}_independent"]
        if column == "race_date":
            left = pd.to_datetime(left, errors="coerce").dt.strftime("%Y-%m-%d")
            right = pd.to_datetime(right, errors="coerce").dt.strftime("%Y-%m-%d")
        key_comparisons[column] = compare_text(column, left, right)
    for column in ("horse_number",):
        key_comparisons[column] = compare_numeric(
            column, merged[f"{column}_builder"], merged[f"{column}_independent"],
        )
    independent_year = pd.to_datetime(merged["race_date_independent"], errors="coerce").dt.year
    key_comparisons["year"] = compare_numeric("year", merged["year"], independent_year)
    key_comparisons["tminus2_cutoff_vs_history_cutoff"] = compare_text(
        "cutoff", merged["tminus2_cutoff"], merged["history_cutoff"],
    )
    key_comparisons["previous_started_api_record_id"] = compare_numeric(
        "previous id", merged["previous_started_api_record_id"], merged["previous_started_api_record_id_asof_t2"],
    )
    key_comparisons["previous_started_date"] = compare_text(
        "previous date", merged["previous_started_date"], merged["previous_started_date_asof_t2"],
    )

    feature_map = {
        "previous_rider_retained": "previous_rider_retained",
        "previous_rider_unknown": "previous_rider_unknown",
        "rider365_delta": "rider365_delta_feature_value",
        "rider365_current_support_log1p": None,
        "rider365_previous_support_log1p": None,
        "rider365_delta_unavailable": "rider365_delta_unavailable",
        "horse_current_rider_rides_log1p": None,
        "horse_current_rider_recency_log1p": None,
        "horse_current_rider_first_observed": "horse_current_rider_first_observed",
        "horse_current_rider_history_unavailable": "horse_current_rider_history_unavailable",
        "rider365_current_support_n": "rider365_current_n",
        "rider365_previous_support_n": "rider365_previous_n",
        "horse_prior_started_n": "horse_past_started_n_asof_t2",
        "horse_current_rider_prior_n": "horse_current_rider_past_started_n",
        "horse_current_rider_recency_days": "horse_current_rider_recency_days_asof_t2",
        "rider365_current_R_diagnostic": "rider365_current_R",
    }
    value_comparisons: dict[str, dict[str, Any]] = {}
    for builder_column, independent_column in feature_map.items():
        if independent_column is not None:
            independent_key = (f"{independent_column}_independent"
                               if independent_column in builder.columns else independent_column)
            expected = merged[independent_key]
        elif builder_column == "rider365_current_support_log1p":
            expected = np.log1p(pd.to_numeric(merged["rider365_current_n"], errors="raise"))
        elif builder_column == "rider365_previous_support_log1p":
            expected = np.log1p(pd.to_numeric(merged["rider365_previous_n"], errors="raise"))
        elif builder_column == "horse_current_rider_rides_log1p":
            expected = np.log1p(pd.to_numeric(merged["horse_current_rider_past_started_n"], errors="raise"))
        else:
            recency = pd.to_numeric(merged["horse_current_rider_recency_days_asof_t2"], errors="coerce").fillna(0)
            expected = np.log1p(recency)
        builder_key = f"{builder_column}_builder" if builder_column in independent.columns else builder_column
        value_comparisons[builder_column] = compare_numeric(
            builder_column, merged[builder_key], expected,
        )

    cache_join = builder[["api_record_id"]].merge(
        cache, on="api_record_id", how="left", validate="one_to_one", indicator=True,
    ).merge(
        independent[["api_record_id", "current_jockey_id"]], on="api_record_id",
        how="left", validate="one_to_one", suffixes=("_cache", "_independent"),
    )
    require(cache_join["_merge"].eq("both").all(), "target runner missing from event rider cache")
    current_id_comparison = compare_text("current event rider ID", cache_join["event_jockey_id"], cache_join["current_jockey_id"])

    missing_or_mismatch = {
        "keys": {name: values["mismatch_rows"] for name, values in key_comparisons.items() if values["mismatch_rows"]},
        "features": {name: values["mismatch_rows"] for name, values in value_comparisons.items()
                     if values["mismatch_rows"]},
        "current_event_jockey_id_mismatch_rows": current_id_comparison["mismatch_rows"],
    }
    source_receipt = json.loads(checked(INDEPENDENT_RECEIPT).read_text(encoding="utf-8"))
    duplicate_receipt = json.loads(checked(H1_DUPLICATE_RECEIPT).read_text(encoding="utf-8"))
    builder_preflight = json.loads(checked(BUILDER_PREFLIGHT).read_text(encoding="utf-8"))
    builder_cache_receipt = json.loads(checked(BUILDER_CACHE_RECEIPT).read_text(encoding="utf-8"))
    source_lock = json.loads(checked(SOURCE_LOCK).read_text(encoding="utf-8"))
    require(source_receipt["status"] == "PASS" and duplicate_receipt["status"] == "PASS",
            "independent source/duplicate receipt is not PASS")
    require(builder_preflight["status"] == "PASS" and builder_cache_receipt["status"] == "PASS",
            "builder source cache or feature preflight is not PASS")
    require(builder_preflight["target_current_outcome_used_in_features"] is False,
            "builder preflight does not certify target outcome exclusion")

    runner_hash = sha256(BUILDER_RUNNERS)
    event_cache_hash = sha256(BUILDER_EVENT_CACHE)
    source_lock_hash = sha256(SOURCE_LOCK)
    prepare_code_hash = sha256(PREPARE_CODE)
    basis_code_hash = sha256(BASIS_CODE)
    hash_checks = {
        "v2_runner_basis_matches_v2_preflight": runner_hash == builder_preflight["runner_basis_sha256"],
        "event_rider_cache_matches_v2_preflight": event_cache_hash == builder_preflight["source_cache_sha256"],
        "event_rider_cache_matches_cache_receipt": event_cache_hash == builder_cache_receipt["cache_sha256"],
        "cache_receipt_matches_v2_preflight": sha256(BUILDER_CACHE_RECEIPT) == builder_preflight["source_cache_receipt_sha256"],
        "source_hashes_matches_v2_preflight": source_lock_hash == builder_preflight["source_lock_sha256"],
        "prepare_code_matches_v2_preflight": prepare_code_hash == builder_preflight["prepare_code_sha256"],
        "basis_code_matches_v2_preflight": basis_code_hash == builder_preflight["basis_code_sha256"],
    }
    feature_status = "PASS" if not any(missing_or_mismatch.values()) else "FAIL"
    lineage_status = "PASS" if all(hash_checks.values()) else "FAIL"
    status = "PASS" if feature_status == lineage_status == "PASS" else "FAIL"
    input_paths = [BUILDER_RUNNERS, BUILDER_EVENT_CACHE, BUILDER_PREFLIGHT, BUILDER_CACHE_RECEIPT,
                   SOURCE_LOCK, PREPARE_CODE, BASIS_CODE, INDEPENDENT_RUNNERS,
                   INDEPENDENT_RECEIPT, H1_DUPLICATE_RECEIPT, Path(__file__).resolve()]
    result = {
        "status": status,
        "runner_value_comparison_status": feature_status,
        "source_lineage_status": lineage_status,
        "scope": "read-only comparison against outputs_prefit_v2; no target labels, fits, predictions, or performance metrics generated",
        "target_labels_read_for_comparison": False,
        "compared_builder_output": str(BUILDER_RUNNERS.relative_to(ROOT)),
        "compared_builder_preflight": str(BUILDER_PREFLIGHT.relative_to(ROOT)),
        "rows_builder": int(len(builder)), "rows_independent": int(len(independent)),
        "api_record_id_key_missing_or_duplicate": 0,
        "key_comparisons": key_comparisons,
        "runner_value_comparisons": value_comparisons,
        "current_event_jockey_id_mismatch_rows": current_id_comparison["mismatch_rows"],
        "mismatches": missing_or_mismatch,
        "tolerance": {"numeric_atol": ABS_TOL, "rtol": 0.0, "exact_text_and_boolean": True},
        "source_hashes": {str(path.relative_to(ROOT)): sha256(path) for path in input_paths},
        "audit_code_sha256": sha256(Path(__file__).resolve()),
        "hash_integrity_checks": hash_checks,
        "builder_hashes_reported_by_feature_preflight": {
            "runner_basis_sha256": builder_preflight["runner_basis_sha256"],
            "source_cache_sha256": builder_preflight["source_cache_sha256"],
            "prepare_code_sha256": builder_preflight["prepare_code_sha256"],
            "basis_code_sha256": builder_preflight["basis_code_sha256"],
        },
        "source_lock_sha256": builder_preflight["source_lock_sha256"],
        "source_lock_path": str(SOURCE_LOCK.relative_to(ROOT)),
        "prepare_code_sha256_current": prepare_code_hash,
        "basis_code_sha256_current": basis_code_hash,
        "exact_duplicate_pair_columns_by_h1": duplicate_receipt["exact_duplicate_column_pairs_across_all_h1_folds"],
        "artifact_paths": {"receipt": str(OUTPUT.relative_to(ROOT))},
    }
    require(status == "PASS", f"builder runner basis differs from independent calculations: {missing_or_mismatch}")
    with OUTPUT.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
    print(json.dumps({
        "status": status, "rows": len(builder), "key_comparisons": key_comparisons,
        "runner_value_mismatches": missing_or_mismatch,
        "current_event_jockey_id_mismatch_rows": current_id_comparison["mismatch_rows"],
        "receipt": str(OUTPUT.relative_to(ROOT)),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
