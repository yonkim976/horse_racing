"""Rebuild the prior-period F1_STYLE6 and trial inputs from frozen sources.

The historical SQLite database is not opened. This script reuses the original
feature-building functions with preserved source snapshots, race-inclusion
ledger, API4/API303 full-point cache and audited API20 trial bundle. It writes
only a receipt in this new study's outputs directory.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs"
PROFILE = ROOT / "jeju/research/20261008_horse_profile_baseline_v1"
FIELD = ROOT / "jeju/research/20261009_field_relative_ability_v1"
FINISH = ROOT / "jeju/research/20261009_finish_history_ablation_v1"
STYLE = ROOT / "jeju/research/20261010_style_history_ablation_v1"
STYLE_AUDIT = ROOT / "jeju/research/20261010_style_history_source_audit_v1"
TRIAL_AUDIT = ROOT / "jeju/research/20261018_debut_trial_source_audit_v1"
TRIAL_STUDY = ROOT / "jeju/research/20261018_debut_trial_ablation_v1"

SOURCE_SNAPSHOT = PROFILE / "outputs_v2/source_snapshot.parquet"
RACE_LEDGER = PROFILE / "outputs_v2/race_inclusion_ledger.csv"
FULL_POINT_CACHE = STYLE_AUDIT / "api4_full_started_point_quality_cache.parquet"
SLOT_CACHE = STYLE_AUDIT / "actual_slot_point_eligibility.parquet"
TRIAL_FEATURES = TRIAL_STUDY / "outputs/features_f1_style6_debut_trial4.parquet"
TRIAL_ROSTER = TRIAL_AUDIT / "outputs/cold_target_roster.parquet"
TRIAL_EVENT_ROWS = TRIAL_AUDIT / "outputs/api20_trial_event_rows.parquet"
TRIAL_LINEAGE = TRIAL_AUDIT / "outputs/cold_target_trial_lineage.parquet"
TRIAL_PEER_LEDGER = TRIAL_AUDIT / "outputs/trial_event_relative_peer_ledger.parquet"

IDENTITY = ["api_record_id", "race_id", "race_date", "year", "horse_id", "horse_number"]
BASE_FEATURES = [
    "distance_m", "grade_raw", "field_n", "observed_starts", "days_since_start",
    "previous_age", "previous_sex", "same_starts", "same_valid_times", "days_since_same",
    "last_time_s", "mean5_s", "valid_n5", "opp_mean5_valid_n",
    "opp_mean5_valid_fraction", "opp_mean5_median_s", "mean5_minus_opp_mean_s",
    "mean5_minus_opp_median_s", "mean5_minus_opp_fast2mean_s", "opp_mean5_faster_n",
    "mean5_rank_fraction", "previous_finish_relative_rank", "previous_top3",
    "previous_result_status", "hist_s1f_relpos_mean5", "hist_s1f_relpos_n",
    "hist_s1f_to_c4_forward_mean5", "hist_s1f_to_c4_pair_n",
    "hist_c4_to_g1f_forward_mean5", "hist_c4_to_g1f_pair_n",
]
ADDED_TRIAL_FEATURES = [
    "trial_peer_relative_time_mean3", "trial_peer_relative_time_n3",
    "trial_days_since_latest_event_pre", "trial_event_count_pre",
]
EXPECTED_ROWS = 52155
EXPECTED_RACES = 5206
EXPECTED_2026_ROWS = 4673


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_fixed_module(name: str, path: Path):
    parent = str(path.parent)
    if parent not in sys.path:
        sys.path.insert(0, parent)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load the fixed feature builder: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def compare_column(left: pd.Series, right: pd.Series, name: str) -> float:
    if pd.api.types.is_numeric_dtype(left) and pd.api.types.is_numeric_dtype(right):
        a = pd.to_numeric(left, errors="raise").to_numpy(dtype="float64", na_value=np.nan)
        b = pd.to_numeric(right, errors="raise").to_numpy(dtype="float64", na_value=np.nan)
        assert np.allclose(a, b, rtol=0, atol=0, equal_nan=True), f"rebuilt value changed: {name}"
        difference = np.abs(a - b)
        return float(np.nanmax(difference)) if np.isfinite(difference).any() else 0.0
    def object_key(value):
        if isinstance(value, np.ndarray):
            value = value.tolist()
        if isinstance(value, (list, tuple)):
            return ("__list__", tuple(object_key(item) for item in value))
        if value is None or value is pd.NA:
            return "<NA>"
        try:
            if bool(pd.isna(value)):
                return "<NA>"
        except (TypeError, ValueError):
            pass
        return str(value)

    a = left.map(object_key).reset_index(drop=True)
    b = right.map(object_key).reset_index(drop=True)
    assert a.equals(b), f"rebuilt text value changed: {name}"
    return 0.0


def compare_frame(
    generated: pd.DataFrame,
    saved: pd.DataFrame,
    columns: list[str],
    label: str,
    key_column: str = "api_record_id",
) -> dict:
    assert len(generated) == len(saved), f"row count differs at stage {label}"
    assert generated[key_column].astype("string").reset_index(drop=True).equals(
        saved[key_column].astype("string").reset_index(drop=True)
    ), f"row order/identity differs at stage {label}"
    errors = {name: compare_column(generated[name], saved[name], name) for name in columns}
    return {"rows": int(len(generated)), "columns_compared": columns, "max_abs_error": max(errors.values(), default=0.0)}


def main() -> dict:
    receipt_path = OUT / "historical_source_rebuild.json"
    assert receipt_path.resolve().is_relative_to(OUT.resolve())
    assert not receipt_path.exists(), "refusing to overwrite the frozen-source rebuild receipt"

    baseline_builder = load_fixed_module("fresh_period_baseline_feature_builder", PROFILE / "run.py")
    field_builder = load_fixed_module("fresh_period_field_relative_builder", FIELD / "run.py")
    finish_builder = load_fixed_module("fresh_period_finish_feature_builder", FINISH / "prepare.py")
    style_builder = load_fixed_module("fresh_period_style_feature_builder", STYLE / "prepare.py")
    trial_builder = load_fixed_module("fresh_period_trial_input_builder", TRIAL_STUDY / "prepare_input.py")

    source = pd.read_parquet(SOURCE_SNAPSHOT)
    ledger = pd.read_csv(RACE_LEDGER)
    assert source.api_record_id.is_unique and len(source) == 92513
    assert source.race_date.max() == "2026-09-19"
    assert ledger.race_id.is_unique and ledger.included.notna().all()
    ledger["included"] = ledger["included"].astype(bool)

    j1_rebuilt = baseline_builder.build_features(source, ledger)
    j1_saved = pd.read_parquet(PROFILE / "outputs_v2/features.parquet")
    j1_columns = list(j1_saved.columns)
    j1_check = compare_frame(j1_rebuilt, j1_saved, j1_columns, "J1 baseline")
    assert len(j1_rebuilt) == EXPECTED_ROWS and j1_rebuilt.race_id.nunique() == EXPECTED_RACES

    r1_rebuilt = field_builder.relative(j1_rebuilt)
    r1_saved = pd.read_parquet(FIELD / "outputs/features.parquet")
    r1_model_columns = list(baseline_builder.BASE) + list(field_builder.EXTRA)
    r1_check = compare_frame(r1_rebuilt, r1_saved, IDENTITY + r1_model_columns, "R1 relative")

    quality_rebuilt = finish_builder.race_quality(source)
    quality_saved = pd.read_parquet(FINISH / "outputs/source_race_quality.parquet")
    quality_check = compare_frame(
        quality_rebuilt, quality_saved,
        [name for name in quality_saved.columns if name != "race_id"],
        "race-history quality", key_column="race_id",
    )
    f1_rebuilt, _ = finish_builder.build_history_features(r1_rebuilt, source, quality_rebuilt)
    f1_saved = pd.read_parquet(FINISH / "outputs/features.parquet")
    f1_columns = finish_builder.CONTRACTS["F1"]
    f1_check = compare_frame(f1_rebuilt, f1_saved, IDENTITY + f1_columns, "F1 finish history")

    full_point_cache = pd.read_parquet(FULL_POINT_CACHE)
    slot_cache = pd.read_parquet(SLOT_CACHE)
    style_builder._validate_cache_shape(full_point_cache, slot_cache)
    full_point_checks = style_builder._validate_full_point_permutations(
        full_point_cache, source, slot_cache
    )
    style_rebuilt, _ = style_builder.build_style_features(f1_rebuilt, source, slot_cache)
    style_saved = pd.read_parquet(STYLE / "outputs/features.parquet")
    style_check = compare_frame(style_rebuilt, style_saved, IDENTITY + BASE_FEATURES, "F1_STYLE6 30-input")
    assert len(BASE_FEATURES) == 30
    assert len(style_rebuilt.loc[style_rebuilt.year.eq(2026)]) == EXPECTED_2026_ROWS

    cold_roster = pd.read_parquet(TRIAL_ROSTER)
    targets = cold_roster.rename(columns={
        "target_api_record_id": "api_record_id",
        "observed_starts_baseline": "observed_starts",
    })[["api_record_id", "race_id", "race_date", "history_cutoff", "horse_id", "observed_starts"]].copy()
    raw_trial_events = pd.read_parquet(TRIAL_EVENT_ROWS)
    normalized_trial_rows = trial_builder._normalize_trial_rows(raw_trial_events)
    trial_rebuilt, trial_slots = trial_builder.add_features(style_rebuilt, targets, normalized_trial_rows)
    trial_saved = pd.read_parquet(TRIAL_FEATURES)
    trial_lineage = pd.read_parquet(TRIAL_LINEAGE)
    trial_peer_ledger = pd.read_parquet(TRIAL_PEER_LEDGER)
    trial_peer_checks = trial_builder._compare_source_lineage(
        trial_slots, trial_lineage, trial_peer_ledger, cold_roster, trial_rebuilt
    )
    trial_check = compare_frame(
        trial_rebuilt, trial_saved, IDENTITY + BASE_FEATURES + ADDED_TRIAL_FEATURES,
        "F1_STYLE6_DEBUT_TRIAL4 34-input",
    )

    inputs = [
        SOURCE_SNAPSHOT, RACE_LEDGER,
        PROFILE / "outputs_v2/features.parquet",
        FIELD / "outputs/features.parquet",
        FINISH / "outputs/source_race_quality.parquet",
        FINISH / "outputs/features.parquet",
        FULL_POINT_CACHE, SLOT_CACHE,
        STYLE / "outputs/features.parquet",
        TRIAL_ROSTER, TRIAL_EVENT_ROWS, TRIAL_LINEAGE, TRIAL_PEER_LEDGER, TRIAL_FEATURES,
    ]
    code_paths = [
        PROFILE / "run.py", FIELD / "run.py", FINISH / "prepare.py", STYLE / "prepare.py",
        TRIAL_STUDY / "feature_core.py", TRIAL_STUDY / "prepare_input.py",
    ]
    receipt = {
        "passed": True,
        "status": "source_to_input_rebuild_from_frozen_artifacts",
        "database_opened": False,
        "database_whole_hash_verifier_called": False,
        "post_2026_09_19_outcome_rows_read": False,
        "new_period_roster_or_outcomes_read": False,
        "candidate_fit_or_calibration_calls": 0,
        "outcome_metrics_computed": False,
        "historical_source_scope": {
            "source_snapshot_max_date": str(source.race_date.max()),
            "source_snapshot_rows": int(len(source)),
            "frozen_included_feature_rows": int(len(style_rebuilt)),
            "frozen_included_races": int(style_rebuilt.race_id.nunique()),
            "historical_2026_rows_rebuilt": int(style_rebuilt.year.eq(2026).sum()),
        },
        "rebuilt_stages": {
            "J1_baseline_from_source_snapshot_and_frozen_inclusion_ledger": j1_check,
            "R1_same_field_relative_builder": r1_check,
            "prior_result_quality_from_source_snapshot": quality_check,
            "F1_same_finish_history_builder": f1_check,
            "F1_STYLE6_same_builder_with_fullpoint_and_slot_cache": style_check,
            "full_point_race_point_checks": int(full_point_checks),
            "trial4_same_feature_core_and_audited_API20_bundle": trial_check,
            "trial_source_lineage_checks": trial_peer_checks,
        },
        "inputs": {str(path.relative_to(ROOT)): sha256(path) for path in inputs},
        "feature_builder_code": {str(path.relative_to(ROOT)): sha256(path) for path in code_paths},
    }
    with receipt_path.open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    return receipt


if __name__ == "__main__":
    print(json.dumps(main(), ensure_ascii=False, indent=2))
