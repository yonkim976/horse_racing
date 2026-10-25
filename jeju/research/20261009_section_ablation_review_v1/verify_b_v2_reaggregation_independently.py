"""Rebuild B's approved 56-cell F1 diagnostic from the frozen row inputs."""
import sys

sys.dont_write_bytecode = True

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
B_DIR = ROOT / "jeju/research/20261009_validation_scope_and_gap_diagnostics_v1"
S1_DIR = ROOT / "jeju/research/20261009_special_condition_audit_v1"
F1_DIR = ROOT / "jeju/research/20261009_finish_history_ablation_v1"
CONDITION = S1_DIR / "outputs/condition_features.parquet"
PREDICTIONS = F1_DIR / "outputs/runner_predictions.parquet"
S1_STATS = S1_DIR / "outputs_f1_supplement/F1_condition_statistics.csv"
INPUT_LOCK = B_DIR / "input_lock.json"
APPROVAL = B_DIR / "APPROVAL_AND_EXECUTION_LOCK.json"
PLAN = B_DIR / "PLAN.md"
APPROVED_PLAN = B_DIR / "PLAN_approved_original.md"
V2 = B_DIR / "F1_gap_residual_by_stratum_v2.csv"
GENERIC = B_DIR / "F1_gap_residual_by_stratum.csv"
V1 = B_DIR / "F1_gap_residual_by_stratum_v1_superseded.csv"
COVERAGE = B_DIR / "F1_gap_group_coverage.csv"
VERIFICATION = B_DIR / "verification.json"
README = B_DIR / "README.md"
DIAGNOSE = B_DIR / "diagnose.py"
DB_PATH = ROOT / "jeju/data/jeju_native_core.sqlite3"
OUT = HERE / "independent_b_v2_outputs"
RECEIPT = HERE / "independent_b_v2_reaggregation.json"
BOOTSTRAPS = 2000
SEED = 20261009
MIN_DAYS_FOR_CI = 10
MIN_ROWS = 100
MIN_RACES = 50
PERIODS = ("2024_2025", "2026_partial")
S1_GROUPS = ("first_return_91_plus", "general")
OTHER_GROUPS = ("second_after_return_le90", "unknown")
DISTANCES = (800, 900, 1000, 1110, 1200, 1300, 1400, 1610)
HISTORY_BUCKETS = ("0", "1_4", "5_plus")
TOP3_BUCKETS = ("top3", "not_top3", "unknown")
KEYS = ("period", "axis", "level", "S1_group")
METRIC_COLUMNS = (
    "n_cohort", "n_F1", "races", "race_days", "mean_residual_y_minus_p_top3",
    "residual_ci95_lo", "residual_ci95_hi", "residual_ci_status",
    "mean_runner_brier", "low_support",
)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_info(path):
    return {"bytes": path.stat().st_size, "sha256": sha256(path)}


def verify_nested_source_lock(input_manifest):
    checked, skipped_large = [], []
    direct_locks = input_manifest["upstream_locks"]
    for lock in direct_locks:
        path = ROOT / lock["path"]
        assert path.stat().st_size == int(lock["bytes"])
        assert sha256(path) == lock["sha256"]
        entries = json.loads(path.read_text(encoding="utf-8"))
        assert len(entries) == int(lock["entries_total"])
        for relative, expected in entries.items():
            file_path = ROOT / relative
            assert file_path.is_file(), relative
            assert file_path.stat().st_size == int(expected["bytes"]), relative
            if relative == "jeju/data/jeju_native_core.sqlite3":
                assert int(expected["bytes"]) == int(input_manifest["database"]["bytes"])
                assert expected["sha256"] == input_manifest["database"]["sha256"]
                skipped_large.append(relative)
                continue
            assert sha256(file_path) == expected["sha256"], relative
            checked.append(relative)
    db = input_manifest["database"]
    assert DB_PATH.stat().st_size == int(db["bytes"])
    for entry in input_manifest["additional_reference_files"]:
        path = ROOT / entry["path"]
        assert path.stat().st_size == int(entry["bytes"]), entry["path"]
        assert sha256(path) == entry["sha256"], entry["path"]
        checked.append(entry["path"])
    return sorted(set(checked)), sorted(set(skipped_large))


def period_for_year(year):
    if int(year) in (2024, 2025):
        return "2024_2025"
    if int(year) == 2026:
        return "2026_partial"
    return None


def history_bucket(value):
    if pd.isna(value):
        return "unknown"
    if value == 0:
        return "0"
    if 1 <= value <= 4:
        return "1_4"
    if value >= 5:
        return "5_plus"
    raise AssertionError(f"unexpected observed_starts value: {value}")


def previous_top3_bucket(value):
    if pd.isna(value):
        return "unknown"
    if value == 1:
        return "top3"
    if value == 0:
        return "not_top3"
    raise AssertionError(f"unexpected previous_top3 value: {value}")


def residual_interval(cell):
    if cell.empty:
        return np.nan, np.nan, "no_rows"
    by_day = cell.assign(_residual=cell.y - cell.p_top3).groupby(
        "race_date", sort=True
    )["_residual"].agg(["sum", "size"])
    days = len(by_day)
    if days < MIN_DAYS_FOR_CI:
        return np.nan, np.nan, "too_few_days"
    sums = by_day["sum"].to_numpy(dtype=np.float64)
    sizes = by_day["size"].to_numpy(dtype=np.float64)
    rng = np.random.default_rng(SEED)
    draws = rng.integers(0, days, size=(BOOTSTRAPS, days))
    samples = sums[draws].sum(axis=1) / sizes[draws].sum(axis=1)
    lo, hi = np.quantile(samples, [0.025, 0.975])
    return float(lo), float(hi), "ok"


def reaggregate(condition, predictions):
    recent = condition.loc[condition.year.isin([2024, 2025, 2026])].copy()
    recent["period"] = recent.year.map(period_for_year)
    recent = recent.loc[recent.period.isin(PERIODS)].copy()
    joined = recent.merge(
        predictions.drop(columns=["variant"]), on="api_record_id", how="left",
        validate="one_to_one", suffixes=("", "_pred"), indicator=True,
    )
    assert joined._merge.eq("both").all()
    for column in ("race_id", "race_date", "horse_id", "year", "y", "distance_m", "observed_starts"):
        right = f"{column}_pred"
        if right in joined:
            if column == "distance_m":
                assert np.allclose(joined[column].to_numpy(float), joined[right].to_numpy(float), rtol=0, atol=0, equal_nan=True)
            else:
                assert joined[column].fillna("<NA>").astype(str).equals(joined[right].fillna("<NA>").astype(str)), column
    assert joined.y.equals(joined.y_pred)
    assert joined.api_record_id.is_unique
    assert joined.p_top3.notna().all() and joined.brier.notna().all()
    assert np.isfinite(joined.p_top3.to_numpy(float)).all()
    assert joined.p_top3.between(0, 1).all()
    expected_brier = (joined.p_top3.to_numpy(float) - joined.y.to_numpy(float)) ** 2
    assert np.allclose(joined.brier.to_numpy(float), expected_brier, rtol=0, atol=1e-12)
    period_rows = {key: int(value) for key, value in joined.groupby("period").size().items()}
    period_races = {key: int(value) for key, value in joined.groupby("period").race_id.nunique().items()}
    assert period_rows == {"2024_2025": 12739, "2026_partial": 4673}
    assert period_races == {"2024_2025": 1291, "2026_partial": 488}
    probability_sum = joined.groupby("race_id", sort=False).p_top3.sum()
    max_prob_sum_error = float((probability_sum - 3).abs().max())
    assert max_prob_sum_error <= 1e-10

    joined["history_bucket"] = joined.observed_starts.map(history_bucket)
    joined["previous_top3_bucket"] = joined.previous_top3.map(previous_top3_bucket)
    joined["distance_bucket"] = joined.distance_m.map(
        lambda value: "unknown" if pd.isna(value) else str(int(value))
    )
    observed_distances = set(joined.loc[joined.distance_m.notna(), "distance_m"].astype(int))
    assert observed_distances.issubset(set(DISTANCES))
    assert set(joined.S1_gap_sequence.dropna().astype(str)).issubset(
        set(S1_GROUPS + OTHER_GROUPS)
    )

    axes = (
        ("distance_m", "distance_bucket", tuple(str(value) for value in DISTANCES)),
        ("observed_starts", "history_bucket", HISTORY_BUCKETS),
        ("previous_top3", "previous_top3_bucket", TOP3_BUCKETS),
    )
    records = []
    for period in PERIODS:
        period_rows_df = joined.loc[joined.period.eq(period)]
        for axis, column, levels in axes:
            for level in levels:
                for group in S1_GROUPS:
                    cell = period_rows_df.loc[
                        period_rows_df[column].eq(level)
                        & period_rows_df.S1_gap_sequence.eq(group)
                    ]
                    n_f1 = int(cell.p_top3.notna().sum())
                    lo, hi, ci_status = residual_interval(cell)
                    records.append({
                        "period": period,
                        "axis": axis,
                        "level": level,
                        "S1_group": group,
                        "n_cohort": int(len(cell)),
                        "n_F1": n_f1,
                        "races": int(cell.race_id.nunique()),
                        "race_days": int(cell.race_date.nunique()),
                        "mean_residual_y_minus_p_top3": float((cell.y - cell.p_top3).mean()) if n_f1 else np.nan,
                        "residual_ci95_lo": lo,
                        "residual_ci95_hi": hi,
                        "residual_ci_status": ci_status,
                        "mean_runner_brier": float(cell.brier.mean()) if n_f1 else np.nan,
                        "low_support": bool(len(cell) < MIN_ROWS or cell.race_id.nunique() < MIN_RACES),
                    })
    strata = pd.DataFrame.from_records(records)
    assert len(strata) == 56
    assert not strata.duplicated(list(KEYS)).any()
    expected_keys = {
        (period, axis, level, group)
        for period in PERIODS
        for axis, _, levels in axes
        for level in levels
        for group in S1_GROUPS
    }
    actual_keys = set(map(tuple, strata[list(KEYS)].itertuples(index=False, name=None)))
    assert actual_keys == expected_keys

    coverage = (
        joined.groupby(["period", "S1_gap_sequence"], dropna=False, sort=True)
        .agg(n_cohort=("api_record_id", "size"), n_F1=("p_top3", "count"),
             races=("race_id", "nunique"), race_days=("race_date", "nunique"))
        .reset_index().rename(columns={"S1_gap_sequence": "S1_group"})
    )
    totals = (
        joined.groupby("period", sort=True)
        .agg(n_cohort=("api_record_id", "size"), n_F1=("p_top3", "count"),
             races=("race_id", "nunique"), race_days=("race_date", "nunique"))
        .reset_index()
    )
    totals["S1_group"] = "all_F1_evaluation_rows"
    coverage = pd.concat([coverage, totals[coverage.columns]], ignore_index=True)
    coverage = coverage.sort_values(["period", "S1_group"], kind="stable").reset_index(drop=True)
    assert len(coverage) == 10
    return joined, strata, coverage, period_rows, period_races, max_prob_sum_error


def compare_numeric_table(expected, observed, key_columns, numeric_columns, string_columns=(), bool_columns=()):
    left = expected.sort_values(key_columns, kind="stable").reset_index(drop=True)
    right = observed.sort_values(key_columns, kind="stable").reset_index(drop=True)
    assert len(left) == len(right), (len(left), len(right))
    for column in key_columns:
        assert left[column].fillna("<NA>").astype(str).equals(right[column].fillna("<NA>").astype(str)), column
    for column in string_columns:
        assert left[column].fillna("<NA>").astype(str).equals(right[column].fillna("<NA>").astype(str)), column
    for column in numeric_columns:
        a = pd.to_numeric(left[column], errors="coerce").to_numpy(dtype=float)
        b = pd.to_numeric(right[column], errors="coerce").to_numpy(dtype=float)
        assert np.allclose(a, b, rtol=0, atol=1e-12, equal_nan=True), column
    for column in bool_columns:
        assert left[column].astype(bool).equals(right[column].astype(bool)), column
    return {"rows": int(len(left)), "exact_keys": True, "numeric_tolerance": 1e-12}


def check_v1_and_generic(v2_cells):
    v2_raw = V2.read_bytes()
    assert V2.read_bytes() == GENERIC.read_bytes()
    # round_trip preserves the exact float text when reconstructing the superseded
    # CSV from the corrected v2 rows; pandas' default parser shortens some digits.
    v2 = pd.read_csv(V2, float_precision="round_trip")
    dup_cells = v2.loc[v2.axis.eq("previous_top3") & v2.level.astype(str).eq("unknown")]
    assert len(dup_cells) == 4
    records = []
    for period in PERIODS:
        block = v2.loc[v2.period.eq(period)]
        records.extend(block.to_dict("records"))
        unknown = block.loc[block.axis.eq("previous_top3") & block.level.astype(str).eq("unknown")]
        records.extend(unknown.to_dict("records"))
    regenerated = pd.DataFrame.from_records(records, columns=v2.columns)
    regenerated_bytes = regenerated.to_csv(index=False, na_rep="NA", lineterminator="\n").encode("utf-8")
    actual_v1_bytes = V1.read_bytes()
    assert actual_v1_bytes == regenerated_bytes
    assert len(pd.read_csv(V1)) == 60
    assert V1.stat().st_size == 8324
    assert sha256(V1) == "1355d5a88c4dbd7cb5d455ade695f91011ac0f1babba7030f78cc42f05634664"
    return {
        "v2_unique_key_rows": int(len(v2_cells)),
        "generic_is_byte_identical_to_v2": True,
        "superseded_v1_rows": 60,
        "duplicate_unknown_rows_recreated": 4,
        "v1_reconstructed_bytes_match_exactly": True,
        "v1_bytes": int(V1.stat().st_size),
        "v1_sha256": sha256(V1),
    }


def main():
    expected_inputs = [CONDITION, PREDICTIONS, S1_STATS, INPUT_LOCK, APPROVAL, PLAN, APPROVED_PLAN, V2, GENERIC, V1, COVERAGE, VERIFICATION, README, DIAGNOSE]
    assert all(path.is_file() for path in expected_inputs)
    input_lock = json.loads(INPUT_LOCK.read_text(encoding="utf-8"))
    approval = json.loads(APPROVAL.read_text(encoding="utf-8"))
    verification = json.loads(VERIFICATION.read_text(encoding="utf-8"))
    checked_lock_paths, skipped_large_paths = verify_nested_source_lock(input_lock)

    approved_plan = approval["plan"]
    approved_plan_snapshot_info = file_info(APPROVED_PLAN)
    current_plan_info = file_info(PLAN)
    current_plan_record = approval["post_execution_current_plan"]
    approved_snapshot_matches_lock = (
        approved_plan_snapshot_info["bytes"] == int(approved_plan["bytes"])
        and approved_plan_snapshot_info["sha256"] == approved_plan["sha256"]
    )
    current_plan_matches_post_execution_record = (
        current_plan_info["bytes"] == int(current_plan_record["bytes"])
        and current_plan_info["sha256"] == current_plan_record["sha256"]
    )
    assert approved_snapshot_matches_lock
    assert current_plan_matches_post_execution_record
    assert current_plan_record["root_approved"] is True
    assert current_plan_record["analysis_unchanged"] is True
    assert current_plan_record["scope"] == "future validation protocol wording only; no change to executed cells, inputs, metrics, or results"
    assert "T−2" in PLAN.read_text(encoding="utf-8") or "T-2" in PLAN.read_text(encoding="utf-8")
    import difflib
    plan_diff = list(difflib.unified_diff(
        APPROVED_PLAN.read_text(encoding="utf-8").splitlines(),
        PLAN.read_text(encoding="utf-8").splitlines(),
        fromfile="approved-original", tofile="post-execution-current", lineterm="",
    ))
    assert len([line for line in plan_diff if line.startswith("-") and not line.startswith("---")]) == 1
    assert len([line for line in plan_diff if line.startswith("+") and not line.startswith("+++")]) == 1

    condition_columns = [
        "api_record_id", "race_id", "race_date", "year", "horse_id", "distance_m",
        "observed_starts", "y", "S1_gap_sequence",
    ]
    prediction_columns = [
        "api_record_id", "race_id", "race_date", "year", "horse_id", "distance_m",
        "observed_starts", "variant", "p_top3", "y", "brier", "previous_top3",
    ]
    condition = pd.read_parquet(CONDITION, columns=condition_columns)
    all_predictions = pd.read_parquet(PREDICTIONS, columns=prediction_columns)
    f1_predictions = all_predictions.loc[all_predictions.variant.eq("F1")].copy()
    assert f1_predictions.api_record_id.is_unique
    assert condition.api_record_id.is_unique
    assert len(condition) == 52155
    assert len(f1_predictions) == 17412

    joined, independent_cells, independent_coverage, period_rows, period_races, probability_error = reaggregate(
        condition, f1_predictions
    )
    output_cells = pd.read_csv(V2)
    output_generic = pd.read_csv(GENERIC)
    output_coverage = pd.read_csv(COVERAGE)
    key_columns = list(KEYS)
    numeric_cells = [
        "n_cohort", "n_F1", "races", "race_days", "mean_residual_y_minus_p_top3",
        "residual_ci95_lo", "residual_ci95_hi", "mean_runner_brier",
    ]
    cells_match = compare_numeric_table(
        independent_cells, output_cells, key_columns, numeric_cells,
        string_columns=["residual_ci_status"], bool_columns=["low_support"],
    )
    generic_match = compare_numeric_table(
        independent_cells, output_generic, key_columns, numeric_cells,
        string_columns=["residual_ci_status"], bool_columns=["low_support"],
    )
    coverage_match = compare_numeric_table(
        independent_coverage, output_coverage,
        ["period", "S1_group"], ["n_cohort", "n_F1", "races", "race_days"],
    )

    # Coverage partitions all recent F1 target rows, including omitted S1 groups.
    group_sum_checks = []
    for period in PERIODS:
        period_cov = independent_coverage.loc[independent_coverage.period.eq(period)]
        total = period_cov.loc[period_cov.S1_group.eq("all_F1_evaluation_rows")].iloc[0]
        group_rows = period_cov.loc[period_cov.S1_group.ne("all_F1_evaluation_rows")]
        assert set(group_rows.S1_group.astype(str)) == set(S1_GROUPS + OTHER_GROUPS)
        assert int(group_rows.n_cohort.sum()) == int(total.n_cohort)
        assert int(group_rows.n_F1.sum()) == int(total.n_F1)
        group_sum_checks.append({
            "period": period,
            "four_disjoint_S1_groups": int(group_rows.n_cohort.sum()),
            "all_f1_evaluation_rows": int(total.n_cohort),
            "four_group_f1_predictions": int(group_rows.n_F1.sum()),
            "all_f1_predictions": int(total.n_F1),
            "exact_partition_match": True,
        })

    # Every one-way axis partitions the two comparison groups into its fixed levels.
    axis_sum_checks = []
    for period in PERIODS:
        for group in S1_GROUPS:
            coverage_row = independent_coverage.loc[
                independent_coverage.period.eq(period)
                & independent_coverage.S1_group.eq(group)
            ].iloc[0]
            for axis in ("distance_m", "observed_starts", "previous_top3"):
                cells = independent_cells.loc[
                    independent_cells.period.eq(period)
                    & independent_cells.S1_group.eq(group)
                    & independent_cells.axis.eq(axis)
                ]
                assert int(cells.n_cohort.sum()) == int(coverage_row.n_cohort), (period, group, axis)
                assert int(cells.n_F1.sum()) == int(coverage_row.n_F1), (period, group, axis)
                axis_sum_checks.append({
                    "period": period,
                    "S1_group": group,
                    "axis": axis,
                    "cell_row_sum": int(cells.n_cohort.sum()),
                    "coverage_row_total": int(coverage_row.n_cohort),
                    "cell_prediction_sum": int(cells.n_F1.sum()),
                    "coverage_prediction_total": int(coverage_row.n_F1),
                    "exact_partition_match": True,
                })

    stats = pd.read_csv(S1_STATS)
    overall_controls = []
    for period in PERIODS:
        for group in S1_GROUPS:
            reference = stats.loc[
                stats.family.eq("S1_gap_sequence")
                & stats.condition.eq(group)
                & stats.period.eq(period)
                & stats.distance_m.isna()
            ]
            assert len(reference) == 1
            ref = reference.iloc[0]
            cov = independent_coverage.loc[
                independent_coverage.period.eq(period)
                & independent_coverage.S1_group.eq(group)
            ].iloc[0]
            axis_distance_cells = independent_cells.loc[
                independent_cells.period.eq(period)
                & independent_cells.axis.eq("distance_m")
                & independent_cells.S1_group.eq(group)
            ]
            residual = float((axis_distance_cells.mean_residual_y_minus_p_top3 * axis_distance_cells.n_F1).sum() / axis_distance_cells.n_F1.sum())
            brier = float((axis_distance_cells.mean_runner_brier * axis_distance_cells.n_F1).sum() / axis_distance_cells.n_F1.sum())
            assert int(cov.n_F1) == int(ref.F1_rows)
            assert int(cov.races) == int(ref.races)
            assert int(cov.race_days) == int(ref.days)
            assert np.isclose(residual, float(ref.F1_residual), rtol=0, atol=1e-12)
            direct = joined.loc[joined.period.eq(period) & joined.S1_gap_sequence.eq(group)]
            direct_residual = float((direct.y - direct.p_top3).mean())
            direct_brier = float(direct.brier.mean())
            assert np.isclose(residual, direct_residual, rtol=0, atol=1e-12)
            assert np.isclose(brier, direct_brier, rtol=0, atol=1e-12)
            assert np.isclose(float(ref.mean_p_F1), float(direct.p_top3.mean()), rtol=0, atol=1e-12)
            overall_controls.append({
                "period": period,
                "S1_group": group,
                "F1_rows": int(cov.n_F1),
                "races": int(cov.races),
                "race_days": int(cov.race_days),
                "residual_direct": direct_residual,
                "residual_distance_cells_weighted": residual,
                "residual_existing_S1_reference": float(ref.F1_residual),
                "mean_probability_direct": float(direct.p_top3.mean()),
                "mean_probability_existing_S1_reference": float(ref.mean_p_F1),
                "mean_brier_direct": direct_brier,
                "mean_brier_distance_cells_weighted": brier,
                "all_control_values_match": True,
            })

    structural_zero = independent_cells.loc[
        independent_cells.axis.eq("observed_starts") & independent_cells.level.eq("0")
        & independent_cells.S1_group.eq("first_return_91_plus")
    ]
    assert len(structural_zero) == 2
    assert structural_zero.n_cohort.eq(0).all() and structural_zero.n_F1.eq(0).all()
    assert structural_zero.mean_residual_y_minus_p_top3.isna().all()
    assert structural_zero.residual_ci_status.eq("no_rows").all()

    # Assert the exact previous_top3 unknown coverage and its 4 expected sparse cells.
    unknown_cells = independent_cells.loc[
        independent_cells.axis.eq("previous_top3") & independent_cells.level.eq("unknown")
    ]
    assert len(unknown_cells) == 4
    assert not unknown_cells.duplicated(list(KEYS)).any()

    version_history = check_v1_and_generic(independent_cells)
    outputs_are_current = {
        name: file_info(path)
        for name, path in {
            "v1": V1, "v2": V2, "generic": GENERIC, "coverage": COVERAGE,
        }.items()
    }
    for name, path in {
        "F1_gap_residual_by_stratum_v1_superseded.csv": V1,
        "F1_gap_residual_by_stratum_v2.csv": V2,
        "F1_gap_residual_by_stratum.csv": GENERIC,
        "F1_gap_group_coverage.csv": COVERAGE,
    }.items():
        assert verification["output_files"][name] == file_info(path), name

    frozen_label_scope = {
        str(value): int(count)
        for value, count in joined.S1_gap_sequence.value_counts(dropna=False).items()
    }
    expected_period_cells = {
        period: {"rows": int(period_rows[period]), "races": int(period_races[period])}
        for period in PERIODS
    }
    mismatches = []
    checks = {
        "F1_recent_cohort_17412_1779_fully_joined": len(joined) == 17412 and joined.race_id.nunique() == 1779,
        "period_support_matches_fixed_expected_counts": period_rows == {"2024_2025": 12739, "2026_partial": 4673}
        and period_races == {"2024_2025": 1291, "2026_partial": 488},
        "candidate_v2_has_exact_56_unique_fixed_keys": len(output_cells) == 56 and not output_cells.duplicated(list(KEYS)).any(),
        "all_56_cells_exactly_reaggregated_including_date_bootstrap_ci": cells_match["exact_keys"],
        "coverage_table_exactly_reaggregated": coverage_match["exact_keys"],
        "four_s1_groups_partition_all_f1_rows_in_each_period": all(x["exact_partition_match"] for x in group_sum_checks),
        "comparison_group_axes_reconcile_to_coverage": all(x["exact_partition_match"] for x in axis_sum_checks),
        "overall_s1_f1_residual_probability_brier_controls_match": all(x["all_control_values_match"] for x in overall_controls),
        "first_return_zero_experience_cells_are_structural_zero": len(structural_zero) == 2,
        "unknown_previous_top3_cells_present_once_per_key": len(unknown_cells) == 4,
        "v1_superseded_60_rows_reconstructed_with_expected_original_hash": version_history["v1_reconstructed_bytes_match_exactly"],
        "generic_current_output_is_byte_identical_to_v2": version_history["generic_is_byte_identical_to_v2"],
        "current_outputs_match_verification_receipt_sha": True,
        "input_source_locks_verified_except_reused_large_db_sha": True,
        "approved_original_and_current_plan_hashes_separately_verified": True,
        "no_new_model_fit": int(verification["new_model_fits"]) == 0,
    }
    assert all(checks.values()), checks

    OUT.mkdir(exist_ok=True)
    cell_out = OUT / "independent_b_v2_56_cells.csv"
    coverage_out = OUT / "independent_b_v2_coverage.csv"
    assert not cell_out.exists() and not coverage_out.exists() and not RECEIPT.exists()
    independent_cells.to_csv(cell_out, index=False, encoding="utf-8", na_rep="NA")
    independent_coverage.to_csv(coverage_out, index=False, encoding="utf-8", na_rep="NA")
    relevant_sources = [
        CONDITION, PREDICTIONS, S1_STATS, INPUT_LOCK, APPROVAL, PLAN, APPROVED_PLAN, V2, GENERIC,
        V1, COVERAGE, VERIFICATION, README, DIAGNOSE,
    ]
    receipt = {
        "review_status": "B_v2_56_cell_diagnostic_independently_reaggregated",
        "candidate_diagnostic_functions_reused": False,
        "model_fit_count": 0,
        "date_bootstrap_recomputed": True,
        "row_and_control_summary": {
            "period_support": expected_period_cells,
            "F1_label_counts_across_periods": frozen_label_scope,
            "coverage_control_partition_by_period": group_sum_checks,
            "fixed_axis_support_partition_checks": axis_sum_checks,
            "existing_S1_overall_control_sums": overall_controls,
            "F1_probability_sum3_max_error": probability_error,
        },
        "cell_matches": cells_match,
        "generic_output_matches": generic_match,
        "coverage_matches": coverage_match,
        "cell_key_inventory": {
            "keys": list(KEYS),
            "unique_row_count": int(len(independent_cells)),
            "expected_count": int(2 * 2 * (len(DISTANCES) + len(HISTORY_BUCKETS) + len(TOP3_BUCKETS))),
            "unknown_previous_top3_rows": int(len(unknown_cells)),
            "first_return_zero_experience_structural_rows": int(len(structural_zero)),
        },
        "version_history": version_history,
        "input_lock_review": {
            "nested_entries_checked": int(len(checked_lock_paths)),
            "large_reused_db_digest_not_rehashed": skipped_large_paths,
            "database_current_size_matches_lock": DB_PATH.stat().st_size == int(input_lock["database"]["bytes"]),
            "approved_original_plan_snapshot": approved_plan_snapshot_info,
            "approved_original_plan_matches_historical_lock": bool(approved_snapshot_matches_lock),
            "current_plan_sha256": current_plan_info["sha256"],
            "current_plan_matches_post_execution_root_approved_record": bool(current_plan_matches_post_execution_record),
            "post_execution_clarification_root_approved": bool(current_plan_record["root_approved"]),
            "analysis_unchanged_attested_in_lock": bool(current_plan_record["analysis_unchanged"]),
            "plan_diff_additions": int(len([line for line in plan_diff if line.startswith("+") and not line.startswith("+++")])),
            "plan_diff_deletions": int(len([line for line in plan_diff if line.startswith("-") and not line.startswith("---")])),
            "clarification_scope_only_no_cell_definition_change_claimed": bool(
                "T−2" in PLAN.read_text(encoding="utf-8") or "T-2" in PLAN.read_text(encoding="utf-8")
            ),
        },
        "checks": checks,
        "outputs": {
            str(path.relative_to(ROOT)): file_info(path)
            for path in (cell_out, coverage_out)
        },
        "references": {
            str(path.relative_to(ROOT)): file_info(path)
            for path in relevant_sources
        },
        "verification_receipt_sha256": sha256(VERIFICATION),
        "review_code_sha256": sha256(Path(__file__)),
    }
    RECEIPT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
