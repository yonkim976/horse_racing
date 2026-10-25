"""Build the fixed six-column section-time extension from the audited slots.

This stage only aggregates source-supported historical values. It does not
score, fit, calibrate, or calculate model evaluation metrics.
"""
import sys

sys.dont_write_bytecode = True

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs"
F1_DIR = ROOT / "jeju/research/20261009_finish_history_ablation_v1"
F1_OUT = F1_DIR / "outputs"
F1_FEATURES = F1_OUT / "features.parquet"
F1_LINEAGE = F1_OUT / "historical_lineage.parquet"
AUDIT_JSON = OUT / "source_availability_audit.json"
SLOT_EXTRACT = OUT / "source_slot_section_times.parquet"
SOURCE_SNAPSHOT = ROOT / "jeju/research/20261008_horse_profile_baseline_v1/outputs_v2/source_snapshot.parquet"
DB_PATH = ROOT / "jeju/data/jeju_native_core.sqlite3"
FIELDS = {"s1f": "jeS1fTime", "g3f": "jeG3fTime", "g1f": "jeG1fTime"}
TIME_STATUSES = {"website_corrected", "api_positive_unreviewed"}


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_new_json(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def main():
    audit = json.loads(AUDIT_JSON.read_text(encoding="utf-8"))
    assert audit["audit_status"] == "availability_only_preflight"
    assert audit["fit_executed"] is False
    assert all(audit["preflight_checks"].values())
    assert audit["quality_source_access"]["slot_extract_sha256"] == sha256(SLOT_EXTRACT)
    for relative, item in audit["references"]["files"].items():
        path = ROOT / relative
        assert path.stat().st_size == item["bytes"] and sha256(path) == item["sha256"], relative

    features = pd.read_parquet(F1_FEATURES)
    lineage = pd.read_parquet(F1_LINEAGE)
    source = pd.read_parquet(SOURCE_SNAPSHOT)
    slots = pd.read_parquet(SLOT_EXTRACT)
    assert (len(features), features.race_id.nunique()) == (52155, 5206)
    assert (len(slots), slots.source_api_record_id.nunique()) == (178459, 50491)
    assert features.api_record_id.is_unique
    assert source.api_record_id.is_unique
    assert not features.horse_id.astype(str).eq("3005648").any()

    lineage_slots = lineage.loc[lineage.history_kind.eq("last5_same_distance_start")].copy()
    lineage_slots = lineage_slots.sort_values(
        ["target_api_record_id", "slot_oldest_to_newest"], kind="stable"
    ).reset_index(drop=True)
    slots = slots.sort_values(
        ["target_api_record_id", "slot_oldest_to_newest"], kind="stable"
    ).reset_index(drop=True)
    assert len(lineage_slots) == len(slots)
    for left, right in [
        (lineage_slots.target_api_record_id, slots.target_api_record_id),
        (lineage_slots.source_api_record_id, slots.source_api_record_id),
        (lineage_slots.slot_oldest_to_newest, slots.slot_oldest_to_newest),
    ]:
        assert np.array_equal(left.to_numpy(), right.to_numpy())
    assert lineage_slots.source_started.eq(True).all()
    assert lineage_slots.target_horse_id.astype(str).eq(lineage_slots.source_horse_id.astype(str)).all()
    assert lineage_slots.target_distance_m.eq(lineage_slots.source_distance_m).all()
    assert lineage_slots.source_race_date.astype(str).le(lineage_slots.target_cutoff.astype(str)).all()
    assert slots.target_horse_id.astype(str).eq(lineage_slots.target_horse_id.astype(str)).all()
    assert slots.target_distance_m.eq(lineage_slots.target_distance_m).all()
    assert slots.target_cutoff.astype(str).eq(lineage_slots.target_cutoff.astype(str)).all()
    assert slots.source_race_date.astype(str).eq(lineage_slots.source_race_date.astype(str)).all()
    assert slots.source_distance_m.eq(lineage_slots.source_distance_m).all()
    assert slots.valid_time.isin([True, False]).all()
    assert slots.groupby("target_api_record_id").slot_oldest_to_newest.apply(
        lambda x: x.astype(int).tolist() == list(range(1, len(x) + 1))
    ).all()
    assert not slots.duplicated(["target_api_record_id", "source_api_record_id"]).any()

    source_index = source.set_index("api_record_id", drop=False)
    assert slots.source_api_record_id.isin(source_index.index).all()
    source_rows = source_index.loc[slots.source_api_record_id.astype(int).to_numpy()]
    assert source_rows.horse_id.astype(str).to_numpy().tolist() == slots.target_horse_id.astype(str).to_list()
    assert source_rows.race_date.astype(str).to_numpy().tolist() == slots.source_race_date.astype(str).to_list()
    assert source_rows.race_distance_m.astype(int).to_numpy().tolist() == slots.source_distance_m.astype(int).to_list()
    assert source_rows.started.astype(bool).to_numpy().tolist() == [True] * len(slots)
    assert source_rows.valid_time.astype(bool).to_numpy().tolist() == slots.valid_time.astype(bool).to_list()

    for field in FIELDS:
        time = pd.to_numeric(slots[f"{field}_time_seconds"], errors="coerce")
        selected = time.notna() & time.gt(0) & slots[f"{field}_time_status"].isin(TIME_STATUSES)
        valid_time = slots.valid_time.astype(bool)
        if field in ("s1f", "g1f"):
            clear = ~slots[f"{field}_race_section_conflict"].astype(bool)
        else:
            clear = pd.Series(True, index=slots.index)
        expected = selected & valid_time & clear
        assert slots[f"{field}_eligible"].astype(bool).equals(expected.astype(bool)), field

    target_ids = features.api_record_id.astype("int64")
    additions = pd.DataFrame({"api_record_id": target_ids})
    for field in FIELDS:
        time_col = f"{field}_time_seconds"
        eligible_col = f"{field}_eligible"
        eligible_values = pd.to_numeric(
            slots.loc[slots[eligible_col].astype(bool), ["target_api_record_id", time_col]][time_col],
            errors="coerce",
        )
        eligible_targets = slots.loc[slots[eligible_col].astype(bool), "target_api_record_id"].astype("int64")
        values = pd.DataFrame({"target_api_record_id": eligible_targets, time_col: eligible_values})
        summary = values.groupby("target_api_record_id", sort=False)[time_col].agg(["mean", "count"])
        summary = summary.reindex(target_ids.to_numpy())
        additions[f"history_{field}_mean5_seconds"] = summary["mean"].to_numpy(dtype=float)
        additions[f"history_{field}_valid_n"] = summary["count"].fillna(0).to_numpy(dtype="int64")

    candidate = features.merge(additions, on="api_record_id", how="left", validate="one_to_one", sort=False)
    assert len(candidate) == len(features)
    assert candidate.api_record_id.astype("int64").equals(features.api_record_id.astype("int64"))
    added_columns = [
        "history_s1f_mean5_seconds", "history_s1f_valid_n",
        "history_g3f_mean5_seconds", "history_g3f_valid_n",
        "history_g1f_mean5_seconds", "history_g1f_valid_n",
    ]
    assert not set(added_columns).intersection(features.columns)
    assert all(pd.api.types.is_numeric_dtype(candidate[column]) for column in added_columns)
    assert candidate["history_s1f_valid_n"].between(0, 5).all()
    assert candidate["history_g3f_valid_n"].between(0, 5).all()
    assert candidate["history_g1f_valid_n"].between(0, 5).all()
    for field in FIELDS:
        n_col, mean_col = f"history_{field}_valid_n", f"history_{field}_mean5_seconds"
        assert candidate.loc[candidate[n_col].eq(0), mean_col].isna().all()
        assert candidate.loc[candidate[n_col].gt(0), mean_col].notna().all()

    feature_contracts = [
        json.loads((F1_OUT / f"F1_{year}/meta.json").read_text(encoding="utf-8"))["features"]
        for year in (2024, 2025, 2026)
    ]
    assert all(columns == feature_contracts[0] for columns in feature_contracts[1:])
    base_columns = feature_contracts[0]
    assert len(base_columns) == 24 and set(base_columns).issubset(candidate.columns)
    assert len(base_columns + added_columns) == 30

    output_features = OUT / "features_f1s.parquet"
    candidate.to_parquet(output_features, index=False)
    reference_files = [
        F1_FEATURES, F1_LINEAGE, SOURCE_SNAPSHOT, DB_PATH,
        HERE / "CONTRACT.md", HERE / "IMPLEMENTATION_PLAN.md",
        HERE / "audit_source_availability.py", HERE / "build_candidate_features.py",
        AUDIT_JSON, SLOT_EXTRACT,
        OUT / "source_availability_by_group.csv", OUT / "source_valid_n_distribution.csv",
    ]
    reference_hashes = {
        str(path.relative_to(ROOT)): {"bytes": path.stat().st_size, "sha256": sha256(path)}
        for path in reference_files
    }
    summary = {
        "passed": True,
        "artifact": "outputs/features_f1s.parquet",
        "candidate_rows": int(len(candidate)),
        "candidate_races": int(candidate.race_id.nunique()),
        "candidate_columns_added": int(len(candidate.columns) - len(features.columns)),
        "candidate_feature_column_count": int(len(added_columns)),
        "candidate_additional_columns": added_columns,
        "f1_input_columns": base_columns,
        "model_columns_f1s": base_columns + added_columns,
        "all_candidate_features_numeric": True,
        "field_specific_missingness_retained": True,
        "n_zero_mean_null_and_partial_n_preserved": True,
        "exact_distance_actual_slot_order_and_t_minus_2_reverified": True,
        "source_quality_eligibility_recomputed_from_audited_slot_extract": True,
        "zero_fill_or_window_backfill": False,
        "fit_executed": False,
        "saved_model_scoring_executed": False,
        "temperature_optimization_executed": False,
        "prediction_metrics_calculated": False,
        "database_write_executed": False,
        "references": reference_hashes,
        "output_sha256": sha256(output_features),
        "builder_code_sha256": sha256(HERE / "build_candidate_features.py"),
    }
    write_new_json(OUT / "candidate_feature_preflight.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
