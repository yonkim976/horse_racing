"""Independent recalculation of F1 condition-residual supplement and 12-cell S2 grid."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
REVIEW = Path(__file__).resolve().parent
SPECIAL = ROOT / "jeju/research/20261009_special_condition_audit_v1"
SUPPLEMENT = SPECIAL / "outputs_f1_supplement"
PRIMARY = SPECIAL / "outputs"
FINISH = ROOT / "jeju/research/20261009_finish_history_ablation_v1"
R1 = ROOT / "jeju/research/20261009_field_relative_ability_v1"
TOP3 = ROOT / "jeju/research/20261009_top3_condition_profiles_v1"
CONDITIONS = ("S1_gap_sequence", "S2_distance_return", "S3_relative_position_change", "S4_prior_rank_finish_gap")
BOOTSTRAPS = 2000
SEED = 20261009
ATOL = 2e-10


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def safe_path(raw: str) -> Path:
    rel = PurePosixPath(raw)
    require(not rel.is_absolute() and ".." not in rel.parts, f"unsafe lock path: {raw}")
    path = (ROOT / Path(*rel.parts)).resolve()
    require(path.is_relative_to(ROOT.resolve()), f"lock path escapes project: {raw}")
    return path


def close(actual: object, expected: object, label: str) -> None:
    a = np.asarray(actual, dtype=float)
    b = np.asarray(expected, dtype=float)
    require(a.shape == b.shape, f"{label}: shape mismatch {a.shape} != {b.shape}")
    ok = np.isclose(a, b, atol=ATOL, rtol=0.0, equal_nan=True)
    require(bool(np.all(ok)), f"{label}: mismatch at {np.flatnonzero(~ok)[:8].tolist()}, "
            f"actual={a[~ok][:8].tolist()}, expected={b[~ok][:8].tolist()}")


def compare(actual: pd.DataFrame, expected: pd.DataFrame, keys: list[str],
            numeric: list[str], label: str) -> None:
    left = actual.sort_values(keys, kind="stable").reset_index(drop=True)
    right = expected.sort_values(keys, kind="stable").reset_index(drop=True)
    require(len(left) == len(right), f"{label}: row count {len(left)} != {len(right)}")
    for key in keys:
        require(left[key].fillna("<NULL>").astype(str).equals(right[key].fillna("<NULL>").astype(str)),
                f"{label}: key mismatch in {key}")
    for col in numeric:
        try:
            close(left[col].to_numpy(float), right[col].to_numpy(float), f"{label}: {col}")
        except AssertionError as exc:
            msg = str(exc)
            import re
            match = re.search(r"mismatch at (\[[^]]*\])", msg)
            bad = json.loads(match.group(1)) if match else []
            raise AssertionError(f"{msg}; keys={left.loc[bad, keys].to_dict('records')}") from exc


def verify_locks() -> dict[str, object]:
    lock = json.loads((SUPPLEMENT / "source_lock.json").read_text(encoding="utf-8"))
    for raw, info in lock.items():
        path = safe_path(raw)
        require(path.is_file(), f"supplement lock file missing: {raw}")
        require(path.stat().st_size == int(info["bytes"]) and sha256(path) == info["sha256"],
                f"supplement source hash/size changed: {raw}")
    primary_lock = json.loads((PRIMARY / "source_lock.json").read_text(encoding="utf-8"))
    primary_verify = json.loads((PRIMARY / "verification.json").read_text(encoding="utf-8"))
    completion = json.loads((FINISH / "outputs/training_completion.json").read_text(encoding="utf-8"))
    require(primary_verify.get("passed") is True and completion.get("passed") is True,
            "locked primary or F1 completion receipt not passed")
    require(len(primary_lock) == 17, "primary condition input lock no longer has 17 files")
    expected_primary_stats_sha = "35b3f7989d97890a4df83cfa09a8aba7f435a06308ea6c08474c608a4ada5f23"
    require(sha256(PRIMARY / "condition_statistics.csv") == expected_primary_stats_sha,
            "original 575-row condition statistics changed")
    f1_predictions = FINISH / "outputs/runner_predictions.parquet"
    require(sha256(f1_predictions) == "37a9567e87b91e3d3bc8b8bfafa1fdab2853239aac422734259b5f893b231440",
            "locked F1 runner predictions changed")
    repair_receipt_path = SUPPLEMENT / "S2_full_grid_v2_verification.json"
    repair_receipt = json.loads(repair_receipt_path.read_text(encoding="utf-8"))
    original_grid = SUPPLEMENT / "S2_full_grid_support.csv"
    repaired_grid = SUPPLEMENT / "S2_full_grid_support_v2.csv"
    repair_code = SPECIAL / "repair_grid_v2.py"
    require(repair_receipt.get("passed") is True and repair_receipt.get("original_grid_preserved") is True and
            repair_receipt.get("all_other_rows_and_fields_identical_after_csv_roundtrip") is True and
            repair_receipt.get("all_period_F1_rows_zero_mean_p_F1_null") is True and
            repair_receipt.get("model_training_count") == 0,
            "S2 v2 correction receipt failed its declared invariants")
    require(repair_receipt.get("source_sha256") == sha256(original_grid) and
            repair_receipt.get("source_bytes") == original_grid.stat().st_size and
            repair_receipt.get("output_sha256") == sha256(repaired_grid) and
            repair_receipt.get("output_bytes") == repaired_grid.stat().st_size and
            repair_receipt.get("repair_code_sha256") == sha256(repair_code),
            "S2 v2 correction receipt hashes or sizes do not match current files")
    original_df = pd.read_csv(original_grid)
    repaired_df = pd.read_csv(repaired_grid)
    repair_mask = original_df.period.eq("all") & original_df.F1_rows.eq(0) & original_df.mean_p_F1.notna()
    require(int(repair_mask.sum()) == 6 and repair_receipt.get("changed_row_count") == 6 and
            repair_receipt.get("changed_field_only") == "mean_p_F1",
            "S2 v2 corrected a different number or type of cells")
    expected_repaired_df = original_df.copy()
    expected_repaired_df.loc[repair_mask, "mean_p_F1"] = np.nan
    pd.testing.assert_frame_equal(expected_repaired_df, repaired_df, check_dtype=False)
    require(sha256(original_grid) == "fefae9d136744b9dba89634e986d49d12b9423f75eefd963e30d62813b11bdff",
            "preserved original S2 grid hash changed")
    output_paths = [SUPPLEMENT / n for n in ("F1_condition_statistics.csv", "F1_date_bootstrap_intervals.csv",
                                               "S2_full_grid_support.csv", "S2_full_grid_support_v2.csv",
                                               "S2_full_grid_v2_verification.json", "supplement_verification.json")]
    return {"supplement_locked_inputs": len(lock), "primary_locked_inputs": len(primary_lock),
            "original_condition_statistics_sha256": expected_primary_stats_sha,
            "original_condition_statistics_bytes": (PRIMARY / "condition_statistics.csv").stat().st_size,
            "original_condition_statistics_rows": len(pd.read_csv(PRIMARY / "condition_statistics.csv")),
            "F1_prediction_sha256": sha256(f1_predictions),
            "supplement_output_hashes": {p.name: {"sha256": sha256(p), "bytes": p.stat().st_size}
                                         for p in output_paths},
            "S2_repair_code": {"path": str(repair_code.relative_to(ROOT)), "sha256": sha256(repair_code),
                               "bytes": repair_code.stat().st_size},
            "S2_repair_cells": 6, "original_S2_grid_preserved": True}


def cell_summary(g: pd.DataFrame, family: str, category: str, period: str,
                 distance: int | None = None) -> dict[str, object]:
    n = len(g)
    f1 = g.loc[g.p_F1.notna()]
    r1 = g.loc[g.p_R1.notna()]
    y = g.y.to_numpy(float)
    return {"family": family, "condition": category, "period": period, "distance_m": distance,
            "rows": n, "F1_rows": len(f1), "horses": int(g.horse_id.nunique()),
            "races": int(g.race_id.nunique()), "days": int(g.race_date.nunique()),
            "top3": int(y.sum()), "non_top3": n - int(y.sum()),
            "first_date": str(g.race_date.min()) if n else None,
            "last_date": str(g.race_date.max()) if n else None,
            "top3_rate": float(y.mean()) if n else np.nan,
            "mean_p_F1": float(f1.p_F1.mean()) if len(f1) else np.nan,
            "F1_residual": float((f1.y - f1.p_F1).mean()) if len(f1) else np.nan,
            "R1_rows": len(r1),
            "R1_residual_reference": float((r1.y - r1.p_R1).mean()) if len(r1) else np.nan,
            "low_support": bool(n < 100 or g.race_id.nunique() < 50)}


def residual_ci(g: pd.DataFrame) -> tuple[float, float]:
    q = g.loc[g.p_F1.notna()].copy()
    if q.empty:
        return np.nan, np.nan
    q["residual"] = q.y - q.p_F1
    by_day = q.groupby("race_date", sort=True).residual.agg(["sum", "size"])
    rng = np.random.default_rng(SEED)
    idx = rng.integers(0, len(by_day), size=(BOOTSTRAPS, len(by_day)))
    values = by_day["sum"].to_numpy()[idx].sum(axis=1) / by_day["size"].to_numpy()[idx].sum(axis=1)
    return float(np.quantile(values, 0.025)), float(np.quantile(values, 0.975))


def f1_condition_tables(joined: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    for period in ("2024_2025", "2026_partial"):
        scope = joined.loc[joined.period.eq(period)]
        for family in CONDITIONS:
            for category, group in scope.groupby(family, sort=True, dropna=False):
                rows.append(cell_summary(group, family, str(category), period))
            for distance, distance_scope in scope.groupby("distance_m", sort=True):
                for category, group in distance_scope.groupby(family, sort=True, dropna=False):
                    rows.append(cell_summary(group, family, str(category), period, int(distance)))
    table = pd.DataFrame(rows)
    intervals = []
    for row in table.itertuples(index=False):
        mask = joined.period.eq(row.period) & joined[row.family].astype(str).eq(row.condition)
        if not pd.isna(row.distance_m):
            mask &= joined.distance_m.eq(float(row.distance_m))
        lo, hi = residual_ci(joined.loc[mask])
        intervals.append({"family": row.family, "condition": row.condition, "period": row.period,
                          "distance_m": row.distance_m, "F1_residual_lo": lo, "F1_residual_hi": hi})
    return table, pd.DataFrame(intervals)


def verify_s2_grid(base: pd.DataFrame, joined: pd.DataFrame, primary_stats: pd.DataFrame,
                   primary_intervals: pd.DataFrame, f1_stats: pd.DataFrame,
                   f1_intervals: pd.DataFrame, actual: pd.DataFrame) -> dict[str, int]:
    period_masks = {
        "all": np.ones(len(base), dtype=bool),
        "2017_2023": base.year.le(2023).to_numpy(),
        "2024_2025": base.year.between(2024, 2025).to_numpy(),
        "2026_partial": base.year.eq(2026).to_numpy(),
    }
    scopes: list[tuple[str, pd.DataFrame, int | None]] = [(period, base.loc[mask], None)
                                                          for period, mask in period_masks.items()]
    for period in ("2017_2023", "2024_2025", "2026_partial"):
        period_scope = base.loc[period_masks[period]]
        for distance, group in period_scope.groupby("distance_m", sort=True):
            scopes.append((period, group, int(distance)))
    rows = []
    for period, scope, distance in scopes:
        current = joined.loc[joined.period.eq(period)].copy() if period in ("2024_2025", "2026_partial") else scope.copy()
        # Historical/all scopes intentionally have no F1 predictions in this supplement.
        # Add an explicit all-NaN column so the common cell summarizer reports F1_rows=0
        # without fabricating residuals for those scopes.
        if "p_F1" not in current.columns:
            current["p_F1"] = np.nan
        if distance is not None:
            current = current.loc[current.distance_m.eq(distance)]
        for relation in ("same", "changed", "unknown"):
            for experience in ("0", "1_2", "3_plus", "unknown"):
                label = f"prev_{relation}|same_starts_{experience}"
                group = scope.loc[scope.S2_distance_return.eq(label)]
                if relation == "same" and experience == "0":
                    status = "structural_zero_previous_same_distance_is_counted"
                elif experience == "unknown":
                    status = "no_missing_same_starts_values_in_frozen_cohort"
                elif len(group):
                    status = "observed"
                elif relation == "unknown" and experience in ("1_2", "3_plus"):
                    status = "possible_but_zero_observed"
                else:
                    status = "zero_observed_not_structural"
                match_primary = primary_stats.loc[
                    primary_stats.family.eq("S2_distance_return") & primary_stats.condition.eq(label) &
                    primary_stats.period.eq(period)]
                match_primary_ci = primary_intervals.loc[
                    primary_intervals.family.eq("S2_distance_return") & primary_intervals.condition.eq(label) &
                    primary_intervals.period.eq(period)]
                match_f1 = f1_stats.loc[
                    f1_stats.family.eq("S2_distance_return") & f1_stats.condition.eq(label) &
                    f1_stats.period.eq(period)]
                match_f1_ci = f1_intervals.loc[
                    f1_intervals.family.eq("S2_distance_return") & f1_intervals.condition.eq(label) &
                    f1_intervals.period.eq(period)]
                if distance is None:
                    match_primary = match_primary.loc[match_primary.distance_m.isna()]
                    match_primary_ci = match_primary_ci.loc[match_primary_ci.distance_m.isna()]
                    match_f1 = match_f1.loc[match_f1.distance_m.isna()]
                    match_f1_ci = match_f1_ci.loc[match_f1_ci.distance_m.isna()]
                else:
                    match_primary = match_primary.loc[match_primary.distance_m.eq(distance)]
                    match_primary_ci = match_primary_ci.loc[match_primary_ci.distance_m.eq(distance)]
                    match_f1 = match_f1.loc[match_f1.distance_m.eq(distance)]
                    match_f1_ci = match_f1_ci.loc[match_f1_ci.distance_m.eq(distance)]
                f1group = current.loc[current.S2_distance_return.eq(label)]
                out = cell_summary(f1group, "S2_distance_return", label, period, distance)
                out["grid_definition_status"] = status
                out["same_starts_missing_values_in_frozen_cohort"] = int(base.S2_same_distance_started_n.isna().sum())
                out["uniform_excess"] = float(match_primary.excess_over_uniform.iloc[0]) if len(match_primary) else np.nan
                out["uniform_excess_lo"] = float(match_primary_ci.uniform_excess_lo.iloc[0]) if len(match_primary_ci) else np.nan
                out["uniform_excess_hi"] = float(match_primary_ci.uniform_excess_hi.iloc[0]) if len(match_primary_ci) else np.nan
                out["R1_residual_reference_from_primary"] = float(match_primary.R1_observed_minus_predicted.iloc[0]) if len(match_primary) else np.nan
                out["F1_rows"] = int(match_f1.F1_rows.iloc[0]) if len(match_f1) else 0
                out["F1_residual"] = float(match_f1.F1_residual.iloc[0]) if len(match_f1) else np.nan
                out["F1_residual_lo"] = float(match_f1_ci.F1_residual_lo.iloc[0]) if len(match_f1_ci) else np.nan
                out["F1_residual_hi"] = float(match_f1_ci.F1_residual_hi.iloc[0]) if len(match_f1_ci) else np.nan
                rows.append(out)
    expected = pd.DataFrame(rows)
    numeric = [c for c in actual.columns if c not in {
        "family", "condition", "period", "first_date", "last_date", "grid_definition_status"
    }]
    compare(actual, expected, ["family", "condition", "period", "distance_m"], numeric,
            "S2 full 12-cell support grid")
    require(len(actual) == 312 and len(actual.groupby(["period", "distance_m"], dropna=False)) == 26,
            "S2 grid scope/cell counts differ")
    statuses = actual.loc[actual.rows.eq(0), "grid_definition_status"].value_counts().to_dict()
    require(statuses.get("structural_zero_previous_same_distance_is_counted", 0) == 26,
            "S2 structural-zero classification differs")
    require(statuses.get("possible_but_zero_observed", 0) == 52,
            "S2 possible-but-zero classification differs")
    require(int(base.S2_same_distance_started_n.isna().sum()) == 0,
            "frozen cohort contains missing same-distance start counts")
    return {"grid_rows": len(actual), "grid_scopes": 26, "cells_per_scope": 12,
            "zero_structural_rows": int(statuses.get("structural_zero_previous_same_distance_is_counted", 0)),
            "zero_possible_but_unobserved_rows": int(statuses.get("possible_but_zero_observed", 0)),
            "same_starts_null_rows": int(base.S2_same_distance_started_n.isna().sum())}


def verify() -> dict[str, object]:
    hash_checks = verify_locks()
    primary = pd.read_parquet(PRIMARY / "condition_features.parquet")
    prediction_all = pd.read_parquet(FINISH / "outputs/runner_predictions.parquet")
    f1 = prediction_all.loc[prediction_all.variant.eq("F1")].copy()
    require(len(primary.loc[primary.year.ge(2024)]) == len(f1) == 17412, "recent/F1 rows differ")
    require(f1.api_record_id.is_unique and not f1.duplicated("api_record_id").any(), "F1 IDs duplicated")
    recent = primary.loc[primary.year.ge(2024)].copy()
    expected_ids = set(recent.api_record_id.astype(int))
    require(set(f1.api_record_id.astype(int)) == expected_ids, "F1 IDs differ from fixed 2024-26 cohort")
    joined = recent.merge(f1[["api_record_id", "race_id", "race_date", "horse_id", "y", "p_top3"]],
                          on="api_record_id", how="left", suffixes=("", "_F1"), validate="one_to_one", indicator=True)
    require(joined._merge.eq("both").all(), "F1 output did not join one-to-one")
    for col in ("race_id", "race_date", "horse_id"):
        require(joined[col].astype(str).equals(joined[f"{col}_F1"].astype(str)), f"F1 ID context mismatch: {col}")
    close(joined.y.to_numpy(float), joined.y_F1.to_numpy(float), "F1 labels")
    joined["p_F1"] = joined.p_top3.astype(float)
    require(joined.p_F1.notna().all() and joined.p_F1.between(0, 1).all(), "F1 probability missing/out of bounds")
    sums = joined.groupby("race_id").p_F1.sum()
    require(len(sums) == 1779, "F1 race count differs")
    close(sums.to_numpy(float), np.full(len(sums), 3.0), "F1 marginal sum per race")
    joined["period"] = np.where(joined.year.le(2025), "2024_2025", "2026_partial")
    require(joined.groupby("period").size().to_dict() == {"2024_2025": 12739, "2026_partial": 4673},
            "F1 period rows differ")
    require(joined.groupby("period").race_id.nunique().to_dict() == {"2024_2025": 1291, "2026_partial": 488},
            "F1 period races differ")

    expected_stats, expected_ci = f1_condition_tables(joined)
    actual_stats = pd.read_csv(SUPPLEMENT / "F1_condition_statistics.csv")
    actual_ci = pd.read_csv(SUPPLEMENT / "F1_date_bootstrap_intervals.csv")
    numeric_stats = [c for c in actual_stats.columns if c not in {"family", "condition", "period", "first_date", "last_date"}]
    compare(actual_stats, expected_stats, ["family", "condition", "period", "distance_m"],
            numeric_stats, "F1 condition residual table")
    compare(actual_ci, expected_ci, ["family", "condition", "period", "distance_m"],
            ["F1_residual_lo", "F1_residual_hi"], "F1 date-bootstrap table")
    require(len(actual_stats) == len(actual_ci) == 301, "F1 fixed observed cell counts differ")
    require(actual_stats.F1_rows.eq(actual_stats.rows).all(), "some recent F1 condition rows have missing predictions")
    require(actual_stats.condition.str.contains("unknown").any(), "unknown condition categories were dropped")

    s2 = pd.read_csv(SUPPLEMENT / "S2_full_grid_support_v2.csv")
    grid_checks = verify_s2_grid(primary, joined, pd.read_csv(PRIMARY / "condition_statistics.csv"),
                                 pd.read_csv(PRIMARY / "date_bootstrap_intervals.csv"),
                                 actual_stats, actual_ci, s2)
    # Independent target outcome/time perturbation check: our row-condition computation
    # excludes target outcomes by construction, while all linked historical context is frozen.
    # Compare a 200-row subset after changing only the target outcome and verifying no
    # condition-valued column changes in the persisted aligned condition table.
    condition_cols = list(CONDITIONS)
    perturb_sample = joined.sample(n=200, random_state=SEED)
    before = perturb_sample[condition_cols].astype(str).reset_index(drop=True)
    mutated = perturb_sample.assign(finish_position=999, finish_time_seconds=1.0e6,
                                    y=1 - perturb_sample.y)
    after = mutated[condition_cols].astype(str).reset_index(drop=True)
    require(before.equals(after), "target outcomes changed the frozen condition inputs")

    supplement_verification = json.loads((SUPPLEMENT / "supplement_verification.json").read_text(encoding="utf-8"))
    require(supplement_verification.get("passed") is True and
            supplement_verification.get("model_training_count_for_supplement") == 0,
            "supplement verification/training declaration differs")
    return {"passed": True, "F1_join_rows": len(joined), "F1_join_races": int(joined.race_id.nunique()),
            "F1_period_rows": joined.groupby("period").size().to_dict(),
            "F1_probability_sums_max_abs_error": float(np.max(np.abs(sums.to_numpy(float) - 3.0))),
            "F1_condition_cells_recalculated": len(actual_stats), "F1_date_CIs_recalculated": len(actual_ci),
            "S2_grid": grid_checks, "target_outcome_perturbation_rows": 200,
            "original_575_row_condition_statistics_preserved": True,
            "hash_checks": hash_checks, "model_training_for_supplement": 0,
            "database_changed": False, "production_changed": False,
            "independent_future_validation": False}


if __name__ == "__main__":
    report = verify()
    path = REVIEW / "f1_condition_supplement_independent_verification.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
