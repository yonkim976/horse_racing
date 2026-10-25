"""Approved one-way, descriptive F1 residual diagnostics for existing S1 groups."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PLAN = HERE / "PLAN.md"
APPROVAL = HERE / "APPROVAL_AND_EXECUTION_LOCK.json"
INPUT_LOCK = HERE / "input_lock.json"
PRIMARY_LOCK = ROOT / "jeju/research/20261009_special_condition_audit_v1/outputs/source_lock.json"
F1_LOCK = ROOT / "jeju/research/20261009_special_condition_audit_v1/outputs_f1_supplement/source_lock.json"
CONDITION_FEATURES = ROOT / "jeju/research/20261009_special_condition_audit_v1/outputs/condition_features.parquet"
PREDICTIONS = ROOT / "jeju/research/20261009_finish_history_ablation_v1/outputs/runner_predictions.parquet"

PERIODS = ["2024_2025", "2026_partial"]
S1_GROUPS = ["first_return_91_plus", "general"]
OTHER_S1_GROUPS = ["second_after_return_le90", "unknown"]
DISTANCES = [800, 900, 1000, 1110, 1200, 1300, 1400, 1610]
START_BUCKETS = ["0", "1_4", "5_plus"]
TOP3_STATES = ["top3", "not_top3", "unknown"]
BOOTSTRAPS = 2000
SEED = 20261009
MIN_DAYS_FOR_CI = 10
MIN_ROWS = 100
MIN_RACES = 50
EXPECTED_PERIOD_ROWS = {"2024_2025": 12739, "2026_partial": 4673}
EXPECTED_PERIOD_RACES = {"2024_2025": 1291, "2026_partial": 488}
FIRST_GENERATED_V1_BYTES = 8324
FIRST_GENERATED_V1_SHA256 = "1355d5a88c4dbd7cb5d455ade695f91011ac0f1babba7030f78cc42f05634664"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(8 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def verify_file(path_text: str, expected_bytes: int, expected_sha: str) -> dict:
    path = ROOT / path_text
    if not path.is_file():
        raise FileNotFoundError(path)
    actual_bytes = path.stat().st_size
    actual_sha = sha256(path)
    if actual_bytes != expected_bytes or actual_sha != expected_sha:
        raise RuntimeError(f"Input lock mismatch: {path_text}")
    return {"path": path_text, "bytes": actual_bytes, "sha256": actual_sha}


def verify_input_locks() -> list[dict]:
    manifest = json.loads(INPUT_LOCK.read_text(encoding="utf-8"))
    approval = json.loads(APPROVAL.read_text(encoding="utf-8"))
    if approval.get("approval_status") != "approved_for_fixed_one_way_cell_aggregation":
        raise RuntimeError("Missing root approval for this fixed analysis")
    plan_lock = approval["plan"]
    if sha256(PLAN) != plan_lock["sha256"] or PLAN.stat().st_size != plan_lock["bytes"]:
        raise RuntimeError("PLAN changed after approval lock")

    verified: dict[str, dict] = {}
    for lock in manifest["upstream_locks"]:
        lock_info = verify_file(lock["path"], lock["bytes"], lock["sha256"])
        verified[lock_info["path"]] = lock_info
        entries = json.loads((ROOT / lock["path"]).read_text(encoding="utf-8"))
        if len(entries) != lock["entries_total"]:
            raise RuntimeError(f"Unexpected upstream lock size: {lock['path']}")
        for relpath, expected in entries.items():
            verified[relpath] = verify_file(relpath, expected["bytes"], expected["sha256"])

    db = manifest["database"]
    verified[db["path"]] = verify_file(db["path"], db["bytes"], db["sha256"])
    for entry in manifest["additional_reference_files"]:
        verified[entry["path"]] = verify_file(entry["path"], entry["bytes"], entry["sha256"])
    return [verified[key] for key in sorted(verified)]


def period_for_year(year: int) -> str | None:
    if year in (2024, 2025):
        return "2024_2025"
    if year == 2026:
        return "2026_partial"
    return None


def history_bucket(value: float) -> str:
    if pd.isna(value):
        return "unknown"
    if value == 0:
        return "0"
    if 1 <= value <= 4:
        return "1_4"
    if value >= 5:
        return "5_plus"
    raise ValueError(f"Unexpected observed_starts value: {value}")


def top3_bucket(value: float) -> str:
    if pd.isna(value):
        return "unknown"
    if value == 1:
        return "top3"
    if value == 0:
        return "not_top3"
    raise ValueError(f"Unexpected previous_top3 value: {value}")


def residual_ci(group: pd.DataFrame) -> tuple[float, float, str]:
    if group.empty:
        return np.nan, np.nan, "no_rows"
    by_day = group.assign(residual=group["y"] - group["p_top3"]).groupby(
        "race_date", sort=True
    )["residual"].agg(["sum", "size"])
    n_days = len(by_day)
    if n_days < MIN_DAYS_FOR_CI:
        return np.nan, np.nan, "too_few_days"
    sums = by_day["sum"].to_numpy(float)
    sizes = by_day["size"].to_numpy(float)
    rng = np.random.default_rng(SEED)
    draws = rng.integers(0, n_days, size=(BOOTSTRAPS, n_days))
    estimates = sums[draws].sum(axis=1) / sizes[draws].sum(axis=1)
    lo, hi = np.quantile(estimates, [0.025, 0.975])
    return float(lo), float(hi), "ok"


def build_tables() -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    condition_columns = [
        "api_record_id", "race_id", "race_date", "year", "horse_id", "distance_m",
        "observed_starts", "y", "S1_gap_sequence",
    ]
    prediction_columns = [
        "api_record_id", "race_id", "race_date", "year", "horse_id", "distance_m",
        "observed_starts", "variant", "p_top3", "y", "brier", "previous_top3",
    ]
    condition = pd.read_parquet(CONDITION_FEATURES, columns=condition_columns)
    predictions = pd.read_parquet(PREDICTIONS, columns=prediction_columns)
    predictions = predictions.loc[predictions.variant.eq("F1")].copy()

    if predictions.api_record_id.duplicated().any():
        raise RuntimeError("F1 prediction api_record_id is not unique")
    if not condition.api_record_id.is_unique:
        raise RuntimeError("S1 condition api_record_id is not unique")

    recent = condition.loc[condition.year.isin([2024, 2025, 2026])].copy()
    recent["period"] = recent.year.map(period_for_year)
    recent = recent.loc[recent.period.isin(PERIODS)].copy()
    joined = recent.merge(
        predictions.drop(columns=["variant"]),
        on="api_record_id", how="left", validate="one_to_one", suffixes=("", "_pred"),
        indicator=True,
    )
    if not joined._merge.eq("both").all():
        raise RuntimeError("F1 predictions do not cover the frozen recent S1 cohort")
    for column in ["race_id", "race_date", "horse_id", "year", "y", "distance_m", "observed_starts"]:
        predicted = f"{column}_pred"
        if predicted in joined:
            left = joined[column]
            right = joined[predicted]
            if column == "distance_m":
                match = np.isclose(left.astype(float), right.astype(float), equal_nan=True)
            else:
                match = left.fillna("<NA>").astype(str).eq(right.fillna("<NA>").astype(str))
            if not bool(np.asarray(match).all()):
                raise RuntimeError(f"Condition/prediction identity mismatch: {column}")
    if not joined.y.eq(joined.y_pred).all():
        raise RuntimeError("F1 outcome labels differ from the frozen S1 cohort")
    if joined.p_top3.isna().any() or joined.brier.isna().any():
        raise RuntimeError("F1 probability or stored Brier loss is missing")
    if not np.isfinite(joined.p_top3).all() or not joined.p_top3.between(0, 1).all():
        raise RuntimeError("F1 probability is invalid")
    if not np.isfinite(joined.brier).all() or not np.allclose(
        joined.brier.to_numpy(float), (joined.p_top3 - joined.y).pow(2).to_numpy(float),
        rtol=0, atol=1e-12,
    ):
        raise RuntimeError("Stored runner-level Brier does not match (p_top3-y)^2")

    period_rows = joined.groupby("period", sort=True).size().to_dict()
    period_races = joined.groupby("period", sort=True).race_id.nunique().to_dict()
    if period_rows != EXPECTED_PERIOD_ROWS or period_races != EXPECTED_PERIOD_RACES:
        raise RuntimeError(f"Unexpected F1 evaluation support: {period_rows}, {period_races}")
    probability_sums = joined.groupby("race_id", sort=False).p_top3.sum()
    max_probability_sum_error = float((probability_sums - 3).abs().max())
    if max_probability_sum_error > 1e-10:
        raise RuntimeError("F1 Top3 probabilities do not sum to 3 per race")

    joined["history_bucket"] = joined.observed_starts.map(history_bucket)
    joined["previous_top3_bucket"] = joined.previous_top3.map(top3_bucket)
    joined["distance_bucket"] = joined.distance_m.map(
        lambda value: "unknown" if pd.isna(value) else str(int(value))
    )
    observed_distances = set(joined.loc[joined.distance_m.notna(), "distance_m"].astype(int))
    if not observed_distances.issubset(set(DISTANCES)):
        raise RuntimeError(f"Unexpected race distance in frozen cohort: {observed_distances}")
    if not set(joined.S1_gap_sequence.dropna().astype(str)).issubset(
        set(S1_GROUPS + OTHER_S1_GROUPS)
    ):
        raise RuntimeError("Unexpected S1 state in the frozen cohort")

    axes = [
        ("distance_m", "distance_bucket", [str(value) for value in DISTANCES]),
        ("observed_starts", "history_bucket", START_BUCKETS),
        ("previous_top3", "previous_top3_bucket", TOP3_STATES),
    ]
    records: list[dict] = []
    for period in PERIODS:
        period_rows_df = joined.loc[joined.period.eq(period)]
        for axis, column, fixed_levels in axes:
            levels = list(fixed_levels)
            if "unknown" not in levels and period_rows_df[column].eq("unknown").any():
                levels.append("unknown")
            for level in levels:
                for condition_name in S1_GROUPS:
                    cell = period_rows_df.loc[
                        period_rows_df[column].eq(level)
                        & period_rows_df.S1_gap_sequence.eq(condition_name)
                    ]
                    n_cohort = len(cell)
                    n_f1 = int(cell.p_top3.notna().sum())
                    races = int(cell.race_id.nunique())
                    days = int(cell.race_date.nunique())
                    lo, hi, ci_status = residual_ci(cell)
                    records.append({
                        "period": period,
                        "axis": axis,
                        "level": level,
                        "S1_group": condition_name,
                        "n_cohort": n_cohort,
                        "n_F1": n_f1,
                        "races": races,
                        "race_days": days,
                        "mean_residual_y_minus_p_top3": float((cell.y - cell.p_top3).mean()) if n_f1 else np.nan,
                        "residual_ci95_lo": lo,
                        "residual_ci95_hi": hi,
                        "residual_ci_status": ci_status,
                        "mean_runner_brier": float(cell.brier.mean()) if n_f1 else np.nan,
                        "low_support": bool(n_cohort < MIN_ROWS or races < MIN_RACES),
                    })
    strata = pd.DataFrame.from_records(records)
    key_columns = ["period", "axis", "level", "S1_group"]
    if strata.duplicated(key_columns).any():
        raise RuntimeError("Duplicate period/axis/level/S1_group key in the fixed table")
    if len(strata) != 56:
        raise RuntimeError(f"Unexpected number of fixed one-way cells: {len(strata)}")

    coverage = (joined.groupby(["period", "S1_gap_sequence"], dropna=False, sort=True)
                .agg(n_cohort=("api_record_id", "size"), n_F1=("p_top3", "count"),
                     races=("race_id", "nunique"), race_days=("race_date", "nunique"))
                .reset_index().rename(columns={"S1_gap_sequence": "S1_group"}))
    totals = (joined.groupby("period", sort=True)
              .agg(n_cohort=("api_record_id", "size"), n_F1=("p_top3", "count"),
                   races=("race_id", "nunique"), race_days=("race_date", "nunique"))
              .reset_index())
    totals["S1_group"] = "all_F1_evaluation_rows"
    coverage = pd.concat([coverage, totals[coverage.columns]], ignore_index=True)
    coverage = coverage.sort_values(["period", "S1_group"], kind="stable").reset_index(drop=True)

    verification = {
        "passed": True,
        "scope": "root-approved one-axis-at-a-time descriptive S1/F1 residual diagnostic",
        "preserved_preflight_stop": {
            "occurred": True,
            "stage": "frozen category validation before residual or loss aggregation and before result writes",
            "reason": "actual coverage-only S1 category is second_after_return_le90",
            "resolution": "root-approved label correction; comparison groups and metrics unchanged",
        },
        "output_review_correction": {
            "occurred": True,
            "reason": "manual review caught a duplicate unknown level in the first generated stratum table",
            "resolution": "deduplicated the fixed level list and regenerated the table; this verification describes the corrected outputs",
        },
        "new_model_fits": 0,
        "period_rows": {key: int(value) for key, value in period_rows.items()},
        "period_races": {key: int(value) for key, value in period_races.items()},
        "all_prediction_ids_unique": True,
        "condition_join_one_to_one": True,
        "all_frozen_recent_rows_have_F1": True,
        "label_and_identity_match": True,
        "stored_brier_formula_match": True,
        "probability_sum3_max_abs_error": max_probability_sum_error,
        "S1_groups_in_coverage": sorted(coverage.S1_group.astype(str).unique().tolist()),
        "stratification_axes": [axis for axis, _, _ in axes],
        "bootstrap": {
            "cluster": "race_date",
            "repetitions": BOOTSTRAPS,
            "seed": SEED,
            "percentiles": [2.5, 97.5],
            "minimum_distinct_days": MIN_DAYS_FOR_CI,
            "small_cell_policy": "point estimates and support retained; CI NA below minimum days",
            "multiple_comparison_adjustment": "none",
        },
        "support_flags": {"n_rows_lt": MIN_ROWS, "n_races_lt": MIN_RACES},
    }
    prior_stats_path = ROOT / "jeju/research/20261009_special_condition_audit_v1/outputs_f1_supplement/F1_condition_statistics.csv"
    prior_stats = pd.read_csv(prior_stats_path)
    reconciliations = []
    for period in PERIODS:
        for condition_name in S1_GROUPS:
            previous = prior_stats.loc[
                prior_stats.family.eq("S1_gap_sequence")
                & prior_stats.condition.eq(condition_name)
                & prior_stats.period.eq(period)
                & prior_stats.distance_m.isna()
            ]
            distance_cells = strata.loc[
                strata.period.eq(period)
                & strata.axis.eq("distance_m")
                & strata.S1_group.eq(condition_name)
            ]
            if len(previous) != 1:
                raise RuntimeError("Existing S1 overall reference cell is not unique")
            n_f1 = int(distance_cells.n_F1.sum())
            weighted_residual = float(
                (distance_cells.mean_residual_y_minus_p_top3 * distance_cells.n_F1).sum() / n_f1
            )
            expected_n = int(previous.F1_rows.iloc[0])
            expected_residual = float(previous.F1_residual.iloc[0])
            if n_f1 != expected_n or not np.isclose(weighted_residual, expected_residual, rtol=0, atol=1e-12):
                raise RuntimeError("Distance cells do not reproduce the existing S1 overall result")
            reconciliations.append({
                "period": period,
                "S1_group": condition_name,
                "n_F1_distance_cells": n_f1,
                "existing_n_F1": expected_n,
                "distance_weighted_residual": weighted_residual,
                "existing_residual": expected_residual,
                "matches_existing_table": True,
            })
    verification["fixed_cell_count"] = len(strata)
    verification["cell_keys_unique"] = True
    verification["overall_S1_reproduction_check_only"] = reconciliations
    return strata, coverage, verification


def reconstruct_first_generated_v1(strata: pd.DataFrame) -> tuple[bytes, str]:
    """Recreate the first generated file's duplicate-unknown bookkeeping bug."""
    records: list[dict] = []
    for period in PERIODS:
        block = strata.loc[strata.period.eq(period)]
        records.extend(block.to_dict("records"))
        duplicate_unknown = block.loc[
            block.axis.eq("previous_top3") & block.level.eq("unknown")
        ]
        records.extend(duplicate_unknown.to_dict("records"))
    v1 = pd.DataFrame.from_records(records, columns=strata.columns)
    raw = v1.to_csv(index=False, na_rep="NA", lineterminator="\n").encode("utf-8")
    return raw, hashlib.sha256(raw).hexdigest()


def main() -> None:
    before = verify_input_locks()
    script_sha = sha256(Path(__file__))
    strata, coverage, verification = build_tables()
    strata_path = HERE / "F1_gap_residual_by_stratum.csv"
    v1_path = HERE / "F1_gap_residual_by_stratum_v1_superseded.csv"
    v2_path = HERE / "F1_gap_residual_by_stratum_v2.csv"
    coverage_path = HERE / "F1_gap_group_coverage.csv"
    v1_bytes, v1_sha = reconstruct_first_generated_v1(strata)
    v1_restored = len(v1_bytes) == FIRST_GENERATED_V1_BYTES and v1_sha == FIRST_GENERATED_V1_SHA256
    if v1_restored:
        if v1_path.exists():
            if v1_path.stat().st_size != FIRST_GENERATED_V1_BYTES or sha256(v1_path) != FIRST_GENERATED_V1_SHA256:
                raise RuntimeError("Existing superseded v1 artifact does not match its recorded hash")
        else:
            v1_path.write_bytes(v1_bytes)
    strata.to_csv(strata_path, index=False, encoding="utf-8", na_rep="NA")
    strata.to_csv(v2_path, index=False, encoding="utf-8", na_rep="NA")
    coverage.to_csv(coverage_path, index=False, encoding="utf-8", na_rep="NA")
    after = verify_input_locks()
    if before != after:
        raise RuntimeError("A locked source changed during the diagnostic")
    if sha256(Path(__file__)) != script_sha:
        raise RuntimeError("Analysis script changed during execution")
    verification["source_lock_verified_before_and_after"] = True
    verification["source_lock_entries_checked"] = len(before)
    verification["strata_rows"] = len(strata)
    verification["coverage_rows"] = len(coverage)
    verification["plan_sha256"] = json.loads(APPROVAL.read_text(encoding="utf-8"))["plan"]["sha256"]
    verification["analysis_script_sha256"] = script_sha
    verification["input_lock_sha256"] = sha256(INPUT_LOCK)
    verification["output_version_history"] = {
        "v1_superseded": {
            "path": v1_path.name if v1_restored else None,
            "reconstructed_from_deterministic_fixed_inputs": v1_restored,
            "bytes": len(v1_bytes),
            "sha256": v1_sha,
            "matches_first_generated_artifact_hash": v1_restored,
            "reason_superseded": "duplicate unknown previous_top3 rows; the first summary had 60 rows instead of the fixed 56",
        },
        "v2_final": {"path": v2_path.name, "unique_cell_keys": True},
        "generic_current_path_is_v2": True,
    }
    verification["output_files"] = {
        path.name: {"bytes": path.stat().st_size, "sha256": sha256(path)}
        for path in (v1_path, v2_path, strata_path, coverage_path) if path.exists()
    }
    (HERE / "verification.json").write_text(
        json.dumps(verification, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "passed": True,
        "strata_rows": len(strata),
        "coverage_rows": len(coverage),
        "source_lock_entries_checked": len(before),
        "output_dir": str(HERE),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
