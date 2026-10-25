"""Validate the frozen source bundle and create the single pre-fit 40-column table."""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal

from feature_core import ADDED_FEATURES, SUPPORTED_DISTANCES, add_relative_history_features
from train_candidate import (
    BASE_COLUMNS,
    BASELINE_REPLAY_PATH,
    FEATURE_PATH,
    OUT,
    ROOT,
    STYLE_OUT,
    YEARS,
    VARIANT,
    sha256,
    write_json_new,
    write_parquet_new,
)


HERE = Path(__file__).resolve().parent
SOURCE_DIR = ROOT / "jeju/research/20261019_distance_section_relative_source_v1"
SOURCE_SCRIPT = SOURCE_DIR / "freeze_distance_section_source.py"
SOURCE_AUDIT_PATH = SOURCE_DIR / "source_audit.json"
SOURCE_MANIFEST_PATH = SOURCE_DIR / "artifact_manifest.json"
BASE_FEATURES_PATH = STYLE_OUT / "features.parquet"
BOOTSTRAP_PATH = ROOT / "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy"
SCHEDULE_SHA256 = "d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd"

FEATURE_OUTPUT_PATH = FEATURE_PATH
SLOT_OUTPUT_PATH = OUT / "target_relative_section_history.parquet"
PROFILE_OUTPUT_PATH = OUT / "target_relative_feature_profiles.parquet"
EXAMPLE_OUTPUT_PATH = OUT / "prefit_feature_examples.csv"
SUPPORT_OUTPUT_PATH = OUT / "prefit_feature_support_by_distance_year.csv"
MEDIAN_OUTPUT_PATH = OUT / "recomputed_reference_race_segment_medians.parquet"
BENCHMARK_OUTPUT_PATH = OUT / "recomputed_source_event_benchmarks.parquet"
PREFLIGHT_PATH = OUT / "source_preflight.json"
LOCK_PATH = OUT / "prepared_lock.json"

SOURCE_USED_FILES = (
    "target_f1_style6_features.parquet",
    "target_distance_roster.parquet",
    "target_last5_lineage.parquet",
    "benchmark_reference_roster.parquet",
    "api4_quality_source_snapshot.parquet",
    "source_race_point_quality_masks.parquet",
    "source_point_order_status_evidence.parquet",
    "source_point_group_status_evidence.parquet",
    "reference_section_intervals.parquet",
    "reference_race_segment_medians.parquet",
    "source_event_benchmark_stats.parquet",
    "target_last5_relative_history.parquet",
    "source_fingerprint_before_after.parquet",
    "section_time_reviews.parquet",
    "nominal_segment_contract.csv",
)


def _safe_source_file(name: str) -> Path:
    """Resolve manifest output names only inside the fixed source directory."""
    candidate_name = Path(name)
    if candidate_name.is_absolute() or candidate_name.name != name or name in {"", ".", ".."}:
        raise AssertionError(f"unsafe source artifact name: {name!r}")
    path = SOURCE_DIR / candidate_name
    if not path.resolve(strict=True).is_relative_to(SOURCE_DIR.resolve(strict=True)):
        raise AssertionError(f"source artifact escaped the frozen source folder: {name}")
    return path


def _safe_root_relative(path_text: str) -> Path:
    candidate = Path(path_text)
    if candidate.is_absolute():
        raise AssertionError(f"expected a root-relative manifest input, got {path_text!r}")
    path = ROOT / candidate
    if not path.resolve(strict=True).is_relative_to(ROOT.resolve(strict=True)):
        raise AssertionError(f"manifest input escaped the workspace: {path_text}")
    return path


def _validate_source_bundle() -> tuple[dict, dict]:
    for path in (SOURCE_SCRIPT, SOURCE_AUDIT_PATH, SOURCE_MANIFEST_PATH):
        if not path.is_file():
            raise FileNotFoundError(path)
    manifest = json.loads(SOURCE_MANIFEST_PATH.read_text(encoding="utf-8"))
    audit = json.loads(SOURCE_AUDIT_PATH.read_text(encoding="utf-8"))
    assert manifest.get("manifest_status") == "frozen_read_only_distance_section_source_snapshot"
    assert audit.get("audit_status") == "read_only_distance_specific_source_snapshot_complete"
    assert audit.get("model_fit_or_score_computed") is False
    assert manifest.get("audit_json_sha256") == sha256(SOURCE_AUDIT_PATH)
    assert manifest.get("inputs") == audit.get("inputs")
    listed_outputs = manifest.get("outputs")
    assert isinstance(listed_outputs, dict) and listed_outputs
    assert set(SOURCE_USED_FILES).issubset(listed_outputs)
    assert set(listed_outputs) == set(audit.get("outputs", {}))
    for name, entry in listed_outputs.items():
        path = _safe_source_file(name)
        assert path.is_file()
        assert int(path.stat().st_size) == int(entry["bytes"])
        assert sha256(path) == entry["sha256"]
        audit_entry = audit["outputs"][name]
        assert int(audit_entry["rows"]) >= 0
        assert int(audit_entry["bytes"]) == int(entry["bytes"])
        assert audit_entry["sha256"] == entry["sha256"]
    for name, entry in manifest["inputs"].items():
        path = _safe_root_relative(entry["path"])
        assert path.is_file()
        assert int(path.stat().st_size) == int(entry["bytes"])
        assert sha256(path) == entry["sha256"], f"frozen upstream source input changed: {name}"
    return manifest, audit


def _segment_number(value: object) -> int:
    text = str(value)
    if not text.startswith("seg_"):
        raise AssertionError(f"unexpected generic segment identifier: {value!r}")
    result = int(text.removeprefix("seg_"))
    if result not in {1, 2, 3, 4, 5}:
        raise AssertionError(f"segment outside fixed five-section contract: {value!r}")
    return result


def _normalize_intervals(frame: pd.DataFrame) -> pd.DataFrame:
    identity = [
        "api_record_id", "race_id", "race_date", "horse_id", "race_distance_m",
        "started", "valid_time",
    ]
    missing = set(identity) - set(frame.columns)
    if missing:
        raise AssertionError(f"frozen reference intervals missing identity: {sorted(missing)}")
    parts = []
    for segment_number in range(1, 6):
        key = f"seg_{segment_number}"
        columns = {
            "raw_delta_seconds": f"{key}_raw_delta_seconds",
            "feature_seconds": f"{key}_feature_seconds",
            "feature_eligible": f"{key}_feature_eligible",
            "quality_eligible": f"{key}_quality_eligible",
            "endpoint_measurement_eligible": f"{key}_endpoint_measurement_eligible",
            "point_quality_clear": f"{key}_point_quality_clear",
            "nominal_length_m": f"{key}_nominal_length_m",
        }
        missing = set(columns.values()) - set(frame.columns)
        if missing:
            raise AssertionError(f"frozen intervals missing {key} columns: {sorted(missing)}")
        part = frame[identity + list(columns.values())].copy().rename(
            columns={
                "race_distance_m": "distance_m",
                **{source_name: target_name for target_name, source_name in columns.items()},
            }
        )
        part["segment_id"] = segment_number
        parts.append(part)
    result = pd.concat(parts, ignore_index=True)
    return result


def _normalize_race_medians(frame: pd.DataFrame) -> pd.DataFrame:
    required = {
        "race_id", "race_date", "race_distance_m", "segment_id",
        "eligible_runner_n", "race_median_seconds", "reference_race_eligible",
    }
    missing = required - set(frame.columns)
    if missing:
        raise AssertionError(f"race median artifact missing columns: {sorted(missing)}")
    result = frame.rename(columns={"race_distance_m": "distance_m"}).copy()
    result["segment_id"] = result.segment_id.map(_segment_number).astype("int64")
    result["distance_m"] = pd.to_numeric(result.distance_m, errors="raise").astype("int64")
    result["eligible_runner_n"] = pd.to_numeric(result.eligible_runner_n, errors="raise").astype("int64")
    return result[[
        "race_id", "race_date", "distance_m", "segment_id", "race_median_seconds",
        "eligible_runner_n", "reference_race_eligible",
    ]]


def _normalize_benchmarks(frame: pd.DataFrame) -> pd.DataFrame:
    required = {
        "source_race_id", "source_race_date", "race_distance_m", "segment_id",
        "reference_cutoff_t_minus_2", "minimum_prior_eligible_races", "prior_eligible_race_n",
        "reference_first_race_date", "reference_last_race_date",
        "mean_of_prior_race_medians_seconds", "benchmark_exists",
    }
    missing = required - set(frame.columns)
    if missing:
        raise AssertionError(f"source benchmark artifact missing columns: {sorted(missing)}")
    result = frame.rename(columns={
        "source_race_id": "race_id",
        "source_race_date": "race_date",
        "race_distance_m": "distance_m",
        "reference_cutoff_t_minus_2": "reference_cutoff_T_minus_2",
        "reference_first_race_date": "reference_first_date",
        "reference_last_race_date": "reference_last_date",
        "mean_of_prior_race_medians_seconds": "mean_of_prior_race_medians",
    }).copy()
    result["segment_id"] = result.segment_id.map(_segment_number).astype("int64")
    for column in ("minimum_prior_eligible_races", "prior_eligible_race_n", "distance_m"):
        result[column] = pd.to_numeric(result[column], errors="raise").astype("int64")
    assert result.minimum_prior_eligible_races.eq(20).all()
    return result[[
        "race_id", "race_date", "distance_m", "segment_id", "reference_cutoff_T_minus_2",
        "minimum_prior_eligible_races", "prior_eligible_race_n", "reference_first_date",
        "reference_last_date", "mean_of_prior_race_medians", "benchmark_exists",
    ]]


def _normalize_target_relative(frame: pd.DataFrame) -> pd.DataFrame:
    required = {
        "target_api_record_id", "slot_oldest_to_newest", "source_api_record_id", "segment_id",
        "raw_delta_seconds", "prior_eligible_race_n", "mean_of_prior_race_medians_seconds",
        "relative_performance_seconds", "relative_performance_eligible", "relative_null_reason",
    }
    missing = required - set(frame.columns)
    if missing:
        raise AssertionError(f"source target-relative artifact missing columns: {sorted(missing)}")
    result = frame.rename(columns={
        "mean_of_prior_race_medians_seconds": "mean_of_prior_race_medians",
        "relative_performance_eligible": "relative_feature_eligible",
    }).copy()
    result["segment_id"] = result.segment_id.map(_segment_number).astype("int64")
    return result


def _relative_profiles(features: pd.DataFrame, roster: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    columns = [
        "api_record_id", "race_id", "race_date", "year", "horse_id", "horse_number",
        "distance_m", "history_cutoff", "last5_same_source_ids", *ADDED_FEATURES,
    ]
    profiles = features.loc[
        features.distance_m.astype("int64").isin(SUPPORTED_DISTANCES), columns
    ].copy()
    profiles["last5_source_api_record_ids_oldest_to_newest"] = profiles.last5_same_source_ids.map(
        lambda values: ";".join(map(str, np.asarray(values, dtype="int64").tolist()))
    )
    profiles = profiles.drop(columns="last5_same_source_ids")
    profiles = profiles.sort_values(
        ["race_date", "race_id", "horse_number", "api_record_id"], kind="stable"
    ).reset_index(drop=True)
    assert len(profiles) == len(roster) and profiles.api_record_id.is_unique

    support_rows = []
    for segment in range(1, 6):
        mean_col = f"hist_relative_seg_{segment}_mean5"
        n_col = f"hist_relative_seg_{segment}_n"
        for (year, distance), group in profiles.groupby(["year", "distance_m"], sort=True):
            support_rows.append({
                "year": int(year),
                "distance_m": int(distance),
                "segment_id": segment,
                "targets": int(len(group)),
                "feature_mean_nonnull_n": int(group[mean_col].notna().sum()),
                "history_slot_n_0": int(group[n_col].eq(0).sum()),
                "history_slot_n_1": int(group[n_col].eq(1).sum()),
                "history_slot_n_2_to_4": int(group[n_col].between(2, 4).sum()),
                "history_slot_n_5": int(group[n_col].eq(5).sum()),
                "mean_relative_performance_seconds": (
                    float(group[mean_col].mean()) if group[mean_col].notna().any() else None
                ),
            })
    support = pd.DataFrame(support_rows)

    example_rows = []
    sort_columns = ["race_date", "race_id", "horse_number", "api_record_id"]
    buckets = (
        ("n0", lambda s: s.eq(0)),
        ("n1", lambda s: s.eq(1)),
        ("n2_to_4", lambda s: s.between(2, 4)),
        ("n5", lambda s: s.eq(5)),
    )
    for distance in SUPPORTED_DISTANCES:
        rows = profiles.loc[profiles.distance_m.eq(distance)].sort_values(sort_columns, kind="stable")
        for segment in range(1, 6):
            n_col = f"hist_relative_seg_{segment}_n"
            mean_col = f"hist_relative_seg_{segment}_mean5"
            for bucket_name, predicate in buckets:
                selected = rows.loc[predicate(rows[n_col])]
                if selected.empty:
                    example_rows.append({
                        "distance_m": distance, "segment_id": segment, "support_bucket": bucket_name,
                        "example_available": False,
                    })
                    continue
                row = selected.iloc[0]
                example_rows.append({
                    "distance_m": int(distance),
                    "segment_id": segment,
                    "support_bucket": bucket_name,
                    "example_available": True,
                    "api_record_id": int(row.api_record_id),
                    "race_id": str(row.race_id),
                    "race_date": str(row.race_date),
                    "horse_id": str(row.horse_id),
                    "horse_number": int(row.horse_number),
                    "history_cutoff_T_minus_2": str(row.history_cutoff),
                    "relative_mean_seconds": (
                        None if pd.isna(row[mean_col]) else float(row[mean_col])
                    ),
                    "eligible_history_slot_n": int(row[n_col]),
                    "last5_source_api_record_ids_oldest_to_newest": row.last5_source_api_record_ids_oldest_to_newest,
                })
    return profiles, support, pd.DataFrame(example_rows)


def _add_file(pinned: dict[str, dict], path: Path, role: str) -> None:
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(ROOT.resolve(strict=True)):
        raise AssertionError(f"locked path escapes workspace: {path}")
    relative = str(resolved.relative_to(ROOT.resolve(strict=True)))
    entry = {"path": relative, "bytes": int(resolved.stat().st_size), "sha256": sha256(resolved), "role": role}
    previous = pinned.get(relative)
    if previous is not None:
        assert previous["sha256"] == entry["sha256"] and previous["bytes"] == entry["bytes"]
        return
    pinned[relative] = entry


def _build_lock(manifest: dict, baseline_receipt: dict, feature_frame: pd.DataFrame,
                source_preflight: dict) -> dict:
    pinned: dict[str, dict] = {}
    _add_file(pinned, BASE_FEATURES_PATH, "saved F1_STYLE6 original 30-input full cohort")
    _add_file(pinned, BASELINE_REPLAY_PATH, "new-path exact saved baseline replay receipt")
    for name in (
        "baseline_replayed_runner_predictions.parquet",
        "baseline_replayed_race_metrics.parquet",
        "baseline_replayed_canonical_max6.parquet",
    ):
        _add_file(pinned, OUT / name, "new-path saved baseline replay result")
    for year in YEARS:
        folder = STYLE_OUT / f"F1_STYLE6_{year}"
        for name in ("top3.txt", "meta.json", "calibration_scores.parquet", "evaluation_scores.parquet"):
            _add_file(pinned, folder / name, "saved F1_STYLE6 fold model or score file")
    for path in (
        STYLE_OUT / "report/runner_predictions.parquet",
        STYLE_OUT / "report/race_metrics.parquet",
        STYLE_OUT / "report/canonical_six_combinations.csv",
    ):
        _add_file(pinned, path, "saved F1_STYLE6 original evaluation report")
    _add_file(pinned, BOOTSTRAP_PATH, "fixed 269-date paired bootstrap schedule")
    for name in (
        "CONTRACT.md", "PLAN.md", "feature_core.py", "prepare_input.py",
        "train_candidate.py", "replay_baseline.py", "selftest_feature_core.py",
    ):
        _add_file(pinned, HERE / name, "study contract or fit-critical code")
    # Pin every frozen source output, including audit-only ledgers and the
    # current-mask-only reconciliation files, so fit verification detects any
    # post-preflight mutation anywhere in the source bundle.
    for name in manifest["outputs"]:
        _add_file(pinned, _safe_source_file(name), "frozen read-only source artifact")
    _add_file(pinned, SOURCE_AUDIT_PATH, "frozen source audit receipt")
    _add_file(pinned, SOURCE_MANIFEST_PATH, "frozen source artifact manifest")
    _add_file(pinned, SOURCE_SCRIPT, "frozen source extraction and contract code")
    for item in manifest["inputs"].values():
        _add_file(pinned, _safe_root_relative(item["path"]), "source-audit pinned upstream input")
    _add_file(pinned, FEATURE_OUTPUT_PATH, "prepared all-distance 40-input table")
    _add_file(pinned, SLOT_OUTPUT_PATH, "independent per-target/per-slot/per-segment residual ledger")
    _add_file(pinned, PROFILE_OUTPUT_PATH, "prefit target profiles without outcomes")
    _add_file(pinned, EXAMPLE_OUTPUT_PATH, "key-selected prefit feature examples")
    _add_file(pinned, SUPPORT_OUTPUT_PATH, "prefit feature support counts")
    _add_file(pinned, MEDIAN_OUTPUT_PATH, "independently recomputed race-level medians")
    _add_file(pinned, BENCHMARK_OUTPUT_PATH, "independently recomputed expanding reference benchmarks")
    _add_file(pinned, PREFLIGHT_PATH, "candidate source and feature preflight receipt")
    return {
        "lock_status": "PREFIT_LOCKED_ROOT_REVIEW_REQUIRED",
        "candidate": VARIANT,
        "feature_count": int(len(BASE_COLUMNS) + len(ADDED_FEATURES)),
        "base_feature_count": int(len(BASE_COLUMNS)),
        "added_feature_count": int(len(ADDED_FEATURES)),
        "full_rows": int(len(feature_frame)),
        "candidate_fit_models": 0,
        "candidate_outcome_metrics_computed": False,
        "source_artifact_manifest_sha256": sha256(SOURCE_MANIFEST_PATH),
        "source_audit_sha256": sha256(SOURCE_AUDIT_PATH),
        "baseline_replay_sha256": sha256(BASELINE_REPLAY_PATH),
        "preflight_sha256": sha256(PREFLIGHT_PATH),
        "baseline_replay_passed": bool(baseline_receipt.get("passed")),
        "fixed_date_schedule_sha256": sha256(BOOTSTRAP_PATH),
        "fixed_date_schedule_expected_sha256": SCHEDULE_SHA256,
        "input_files": pinned,
        "prepared_feature_sha256": sha256(FEATURE_OUTPUT_PATH),
        "prepared_slot_ledger_sha256": sha256(SLOT_OUTPUT_PATH),
        "prepared_reference_median_sha256": sha256(MEDIAN_OUTPUT_PATH),
        "prepared_reference_benchmark_sha256": sha256(BENCHMARK_OUTPUT_PATH),
        "source_preflight_summary": source_preflight,
    }


def prepare() -> dict:
    if any(path.exists() for path in (
        FEATURE_OUTPUT_PATH, SLOT_OUTPUT_PATH, PROFILE_OUTPUT_PATH, EXAMPLE_OUTPUT_PATH,
        SUPPORT_OUTPUT_PATH, MEDIAN_OUTPUT_PATH, BENCHMARK_OUTPUT_PATH, PREFLIGHT_PATH, LOCK_PATH,
    )):
        raise FileExistsError("prefit output exists; refusing to overwrite this study's artifacts")
    manifest, audit = _validate_source_bundle()
    assert sha256(BOOTSTRAP_PATH) == SCHEDULE_SHA256
    schedule = np.load(BOOTSTRAP_PATH, allow_pickle=False)
    assert schedule.shape == (2000, 269)
    assert BASELINE_REPLAY_PATH.is_file(), "saved baseline replay must pass before preparation"
    baseline_receipt = json.loads(BASELINE_REPLAY_PATH.read_text(encoding="utf-8"))
    assert baseline_receipt.get("passed") is True
    assert baseline_receipt.get("baseline_models_reloaded") == 3
    assert baseline_receipt.get("runner_rows_reproduced") == 17412
    assert baseline_receipt.get("distinct_races_reproduced") == 1779
    assert baseline_receipt.get("candidate_fit_models") == 0
    assert baseline_receipt.get("candidate_outcome_metrics_computed") is False

    original = pd.read_parquet(BASE_FEATURES_PATH)
    source_base = pd.read_parquet(_safe_source_file("target_f1_style6_features.parquet"))
    assert len(original) == len(source_base) == 52155
    assert original.api_record_id.is_unique and source_base.api_record_id.is_unique
    assert original.columns.tolist() == source_base.columns.tolist()
    assert_frame_equal(
        original.reset_index(drop=True), source_base.reset_index(drop=True),
        check_dtype=False, check_exact=True,
    )
    assert list(BASE_COLUMNS) == json.loads(
        (STYLE_OUT / "F1_STYLE6_2024/meta.json").read_text(encoding="utf-8")
    )["features"]
    assert len(BASE_COLUMNS) == 30 and len(ADDED_FEATURES) == 10

    target_roster = pd.read_parquet(_safe_source_file("target_distance_roster.parquet"))
    target_slots = pd.read_parquet(_safe_source_file("target_last5_lineage.parquet"))
    source_interval_raw = pd.read_parquet(_safe_source_file("reference_section_intervals.parquet"))
    source_race_medians = _normalize_race_medians(
        pd.read_parquet(_safe_source_file("reference_race_segment_medians.parquet"))
    )
    source_benchmarks = _normalize_benchmarks(
        pd.read_parquet(_safe_source_file("source_event_benchmark_stats.parquet"))
    )
    source_target_relative = _normalize_target_relative(
        pd.read_parquet(_safe_source_file("target_last5_relative_history.parquet"))
    )
    source_intervals = _normalize_intervals(source_interval_raw)

    features, slot_ledger, medians, benchmarks = add_relative_history_features(
        source_base,
        target_roster,
        target_slots,
        source_intervals,
        source_race_segment_medians=source_race_medians,
        source_benchmark_stats=source_benchmarks,
        source_target_relative_history=source_target_relative,
    )
    assert features[BASE_COLUMNS].equals(original[BASE_COLUMNS]), "original baseline inputs changed"
    assert features.api_record_id.astype("int64").tolist() == original.api_record_id.astype("int64").tolist()
    assert len(features) == 52155 and features.race_id.nunique() == 5206
    assert features.year.isin(range(2017, 2027)).all()
    assert features.loc[features.year.ge(2024)].shape[0] == 17412
    assert features.loc[features.year.ge(2024), "race_id"].nunique() == 1779
    assert len(features.columns) == len(original.columns) + 10
    target_eval = features.loc[
        features.year.ge(2024) & features.distance_m.astype("int64").isin(SUPPORTED_DISTANCES)
    ]
    assert len(target_roster) == 38193
    assert len(target_eval) == 14714 and target_eval.race_id.nunique() == 1503
    expected_eval = {
        (2024, 900): (480, 48), (2024, 1000): (1694, 170),
        (2024, 1110): (1766, 178), (2024, 1200): (1019, 103),
        (2025, 900): (1046, 106), (2025, 1000): (1947, 196),
        (2025, 1110): (1751, 178), (2025, 1200): (739, 79),
        (2026, 900): (938, 97), (2026, 1000): (1372, 142),
        (2026, 1110): (1208, 126), (2026, 1200): (754, 80),
    }
    observed_eval = target_eval.groupby(["year", "distance_m"], sort=True).agg(
        rows=("api_record_id", "size"), races=("race_id", "nunique")
    )
    for key, expected in expected_eval.items():
        row = observed_eval.loc[key]
        assert (int(row.rows), int(row.races)) == expected, (key, row.to_dict())
    assert len(target_eval[target_eval.distance_m.eq(900)]) == 2464
    assert len(target_eval[target_eval.distance_m.eq(1000)]) == 5013
    assert len(target_eval[target_eval.distance_m.eq(1110)]) == 4725
    assert len(target_eval[target_eval.distance_m.eq(1200)]) == 2512

    profiles, support, examples = _relative_profiles(features, target_roster)
    preflight = {
        "passed": True,
        "status": "PASS_PREFIT_SOURCE_AND_FEATURE_PREPARATION",
        "candidate": VARIANT,
        "baseline": "saved F1_STYLE6; three saved models reloaded, no retraining",
        "baseline_replay_sha256": sha256(BASELINE_REPLAY_PATH),
        "baseline_fit_models": 0,
        "candidate_fit_models": 0,
        "candidate_outcome_metrics_computed": False,
        "base_feature_values_exact": True,
        "candidate_feature_count": int(len(BASE_COLUMNS) + len(ADDED_FEATURES)),
        "base_feature_count": int(len(BASE_COLUMNS)),
        "added_feature_count": int(len(ADDED_FEATURES)),
        "full_rows": int(len(features)),
        "full_races": int(features.race_id.nunique()),
        "full_base_columns_exact": original.columns.tolist() == source_base.columns.tolist(),
        "row_order_exact": features.api_record_id.astype("int64").tolist()
            == original.api_record_id.astype("int64").tolist(),
        "target_roster_rows": int(len(target_roster)),
        "target_slot_rows": int(len(target_slots)),
        "relative_target_slot_segment_rows": int(len(slot_ledger)),
        "reference_rows": int(len(source_intervals) // 5),
        "reference_starter_rows": int(source_interval_raw.api_record_id.nunique()),
        "reference_races": int(source_interval_raw.race_id.nunique()),
        "reference_date_min": str(source_interval_raw.race_date.min()),
        "reference_date_max": str(source_interval_raw.race_date.max()),
        "independent_medians_compared": int(len(medians)),
        "independent_benchmarks_compared_source_slot_events": int(len(source_benchmarks)),
        "source_target_residual_rows_compared": int(len(source_target_relative)),
        "target_eval_rows_4_distances": int(len(target_eval)),
        "target_eval_races_4_distances": int(target_eval.race_id.nunique()),
        "target_eval_by_year_distance": {
            f"{year}_{distance}": {"rows": int(row.rows), "races": int(row.races)}
            for (year, distance), row in observed_eval.iterrows()
        },
        "fixed_date_bootstrap_sha256": sha256(BOOTSTRAP_PATH),
        "fixed_date_bootstrap_shape": list(schedule.shape),
        "root_fit_approval_present": False,
        "features": ADDED_FEATURES,
        "feature_support_by_distance_year": SUPPORT_OUTPUT_PATH.name,
        "source_artifact_manifest_sha256": sha256(SOURCE_MANIFEST_PATH),
        "source_audit_sha256": sha256(SOURCE_AUDIT_PATH),
    }
    assert preflight["fixed_date_bootstrap_sha256"] == SCHEDULE_SHA256

    # All output material is produced only after source files, features, counts,
    # independent references, and the prefit baseline have passed validation.
    write_parquet_new(FEATURE_OUTPUT_PATH, features)
    write_parquet_new(SLOT_OUTPUT_PATH, slot_ledger)
    write_parquet_new(PROFILE_OUTPUT_PATH, profiles)
    examples.to_csv(EXAMPLE_OUTPUT_PATH, index=False)
    support.to_csv(SUPPORT_OUTPUT_PATH, index=False)
    write_parquet_new(MEDIAN_OUTPUT_PATH, medians)
    write_parquet_new(BENCHMARK_OUTPUT_PATH, benchmarks)
    write_json_new(PREFLIGHT_PATH, preflight)

    # Re-read all source artifact hashes before writing the lock; a concurrent
    # source change invalidates this preparation.
    manifest_after, audit_after = _validate_source_bundle()
    assert sha256(SOURCE_MANIFEST_PATH) == preflight["source_artifact_manifest_sha256"]
    assert sha256(SOURCE_AUDIT_PATH) == preflight["source_audit_sha256"]
    assert manifest_after == manifest and audit_after == audit
    lock = _build_lock(manifest, baseline_receipt, features, preflight)
    write_json_new(LOCK_PATH, lock)
    print(json.dumps({"preflight": preflight, "prepared_lock_sha256": sha256(LOCK_PATH)},
                     ensure_ascii=False, indent=2, default=lambda v: v.item() if isinstance(v, np.generic) else str(v)))
    return preflight


if __name__ == "__main__":
    prepare()
