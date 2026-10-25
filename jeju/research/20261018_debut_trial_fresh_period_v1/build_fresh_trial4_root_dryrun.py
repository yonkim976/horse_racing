"""Build frozen fresh-period trial4 inputs and compare against root references.

This preflight does not load outcomes, run model prediction, calculate metrics,
fit/calibrate a model, or open a database. All writes stay in this study folder.
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
SOURCE = ROOT / "jeju/research/20261018_debut_trial_fresh_source_v1/outputs"
ROOT_REVIEW = ROOT / "jeju/research/20261018_debut_trial_fresh_rootreview_v1"
OLD_STUDY = ROOT / "jeju/research/20261018_debut_trial_ablation_v1"
OUT = HERE / "outputs"

BASE30_PATH = OUT / "root_dryrun_fresh_features_30.parquet"
SOURCE_MANIFEST = SOURCE / "audit_manifest.json"
TRIAL_SOURCE = SOURCE / "api20_linked_full_peer_event_rows.parquet"
TARGET_SOURCE = SOURCE / "cold_target_roster.parquet"
ROOT_BASE30 = ROOT_REVIEW / "ROOT_FRESH_BASE30.parquet"
ROOT_INPUT34 = ROOT_REVIEW / "ROOT_FRESH_FROZEN_INPUT34.parquet"
ROOT_TRIAL4 = ROOT_REVIEW / "ROOT_FRESH_TRIAL4.parquet"
ROOT_TRIAL_SLOTS = ROOT_REVIEW / "ROOT_FRESH_TRIAL_SLOTS.parquet"
FEATURE_CORE = OLD_STUDY / "feature_core.py"

OUT_FEATURES = OUT / "fresh_features_34_root_dryrun.parquet"
OUT_SLOTS = OUT / "fresh_trial_slots_root_dryrun.parquet"
OUT_RECEIPT = OUT / "fresh_trial4_build.json"

SOURCE_MANIFEST_SHA256 = "c3e08c29c6acd8c263b64649e4816e287427338464af966c103623084f56e44a"
TRIAL_SOURCE_SHA256 = "9ab64bd4f23e975af8a7912cf08626c91036172930bc03ce51aa0f75fa87e2b7"

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
TRIAL_FEATURES = [
    "trial_peer_relative_time_mean3",
    "trial_peer_relative_time_n3",
    "trial_days_since_latest_event_pre",
    "trial_event_count_pre",
]
MODEL_FEATURES = BASE_FEATURES + TRIAL_FEATURES
STRING_FEATURES = {"grade_raw", "previous_sex", "previous_result_status"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_module(name: str, path: Path):
    if str(path.parent) not in sys.path:
        sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load frozen feature core: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def strict_bool(series: pd.Series, name: str) -> pd.Series:
    if series.isna().any():
        raise AssertionError(f"{name} contains NULL")
    if pd.api.types.is_bool_dtype(series):
        return series.astype(bool)
    mapped = series.map({True: True, False: False, 1: True, 0: False, "True": True, "False": False, "1": True, "0": False})
    if mapped.isna().any():
        raise AssertionError(f"{name} contains an unknown boolean token")
    return mapped.astype(bool)


def compare_features(left: pd.DataFrame, right: pd.DataFrame, features: list[str], name: str) -> dict:
    lhs = left.sort_values("api_record_id", kind="stable").reset_index(drop=True)
    rhs = right.sort_values("api_record_id", kind="stable").reset_index(drop=True)
    lhs_ids = pd.to_numeric(lhs.api_record_id, errors="raise").astype("int64")
    rhs_ids = pd.to_numeric(rhs.api_record_id, errors="raise").astype("int64")
    if not lhs_ids.equals(rhs_ids):
        raise AssertionError(f"{name}: row IDs differ")
    errors: dict[str, float] = {}
    for column in features:
        if column in STRING_FEATURES:
            a = lhs[column].astype("string").fillna("<NULL>")
            b = rhs[column].astype("string").fillna("<NULL>")
            if not a.equals(b):
                raise AssertionError(f"{name}: string feature differs: {column}")
            errors[column] = 0.0
        else:
            a = pd.to_numeric(lhs[column], errors="coerce").to_numpy(dtype="float64", na_value=np.nan)
            b = pd.to_numeric(rhs[column], errors="coerce").to_numpy(dtype="float64", na_value=np.nan)
            if not np.allclose(a, b, rtol=0, atol=1e-12, equal_nan=True):
                raise AssertionError(f"{name}: numeric feature differs: {column}")
            delta = np.abs(a - b)
            errors[column] = float(np.nanmax(delta)) if np.isfinite(delta).any() else 0.0
    return {
        "rows": int(len(lhs)),
        "columns": features,
        "max_abs_error": max(errors.values(), default=0.0),
        "column_errors": errors,
    }


def normalize_trial_rows(peers: pd.DataFrame) -> pd.DataFrame:
    required_audit_columns = {
        "api_record_id", "trial_date", "meet_code", "trial_number", "horse_id",
        "breed_label_raw", "breed_assessment", "raw_daySerial", "raw_daySerial_json_type",
        "raw_ord", "raw_ord_json_type", "raw_rcTime", "raw_passFlag",
        "raw_trainDate_matches_normalized", "raw_trainNo_matches_normalized",
        "explicit_jeju_native", "ord_integer_1_89", "rcTime_finite_positive",
        "passFlag_known_allowlist", "event_key_valid_for_candidate", "event_daySerial_invariant",
        "event_unique_horse_ids", "event_unique_natural_keys", "normalized_event_key",
        "payload_json", "payload_sha256", "source_artifact_id", "record_index",
    }
    missing = required_audit_columns - set(peers.columns)
    if missing:
        raise AssertionError(f"audited API20 source missing fields: {sorted(missing)}")
    if len(peers) != 121 or peers.api_record_id.nunique() != 121:
        raise AssertionError("API20 frozen source must contain 121 unique peer rows")
    if peers.payload_json.isna().any() or peers.payload_sha256.isna().any():
        raise AssertionError("API20 raw payload/provenance is incomplete")
    if not peers.breed_label_raw.astype("string").eq("제주").all():
        raise AssertionError("trial peer rows must be exact raw majong=제주")
    if not peers.breed_assessment.astype("string").eq("api_native_label").all():
        raise AssertionError("trial peer rows must preserve native API label assessment")

    bool_columns = [
        "raw_trainDate_matches_normalized", "raw_trainNo_matches_normalized",
        "explicit_jeju_native", "ord_integer_1_89", "rcTime_finite_positive",
        "passFlag_known_allowlist", "event_key_valid_for_candidate", "event_daySerial_invariant",
        "event_unique_horse_ids", "event_unique_natural_keys",
    ]
    for column in bool_columns:
        peers[column] = strict_bool(peers[column], column)
    required_source_gates = [
        "raw_trainDate_matches_normalized", "raw_trainNo_matches_normalized",
        "explicit_jeju_native", "event_key_valid_for_candidate", "event_daySerial_invariant",
        "event_unique_horse_ids", "event_unique_natural_keys",
    ]
    for column in required_source_gates:
        if not peers[column].all():
            raise AssertionError(f"API20 source quality gate failed: {column}")

    if not peers.raw_daySerial_json_type.astype("string").eq("integer").all():
        raise AssertionError("raw daySerial type differs from frozen integer source contract")
    if not peers.raw_ord_json_type.astype("string").isin(["integer", "string", "absent", "null"]).all():
        raise AssertionError("raw ord type outside frozen source scope")
    if not peers.raw_rcTime_json_type.astype("string").isin(["integer", "number", "string", "absent", "null"]).all():
        raise AssertionError("raw rcTime type outside frozen source scope")
    if peers.raw_daySerial.isna().any():
        raise AssertionError("required raw API20 daySerial contains NULL")

    trial_date = peers.trial_date.astype("string")
    meet = pd.to_numeric(peers.meet_code, errors="raise").astype("int64")
    trial_no = pd.to_numeric(peers.trial_number, errors="raise").astype("int64")
    if not meet.eq(2).all():
        raise AssertionError("API20 trial data must be restricted to Jeju meet=2")
    expected_normalized_key = trial_date + "_2_" + trial_no.astype("string")
    if not peers.normalized_event_key.astype("string").reset_index(drop=True).equals(
        expected_normalized_key.reset_index(drop=True)
    ):
        raise AssertionError("audited underscore event identity differs from normalized source fields")

    ord_values = peers.raw_ord.astype("string")
    times = pd.to_numeric(peers.raw_rcTime, errors="coerce")
    time_eligible = (
        peers.ord_integer_1_89
        & peers.rcTime_finite_positive
        & peers.passFlag_known_allowlist
    )
    normalized = pd.DataFrame({
        "source_api_record_id": pd.to_numeric(peers.api_record_id, errors="raise").astype("int64"),
        "trial_event_key": trial_date + "|2|" + trial_no.astype("string"),
        "trial_event_order": trial_no,
        "trial_date": trial_date,
        "meet_code": meet,
        "trial_day_serial": pd.to_numeric(peers.raw_daySerial, errors="raise").astype("int64"),
        "horse_id": peers.horse_id.astype("string"),
        "breed_label_raw": peers.breed_label_raw.astype("string"),
        "finish_time_seconds": times.astype("float64"),
        # The audited table stores the exact raw scalar as text alongside its
        # JSON type; canonical numeric strings are accepted by the frozen core.
        "trial_ord_raw": ord_values,
        "trial_judgment_raw": peers.raw_passFlag.astype("string"),
        "time_eligible": time_eligible.astype(bool),
    })
    if not normalized.time_eligible.equals(time_eligible.astype(bool)):
        raise AssertionError("API20 eligibility was not derived from the audited allowlist gates")
    return normalized


def compare_trial_slots(generated: pd.DataFrame, expected: pd.DataFrame) -> dict:
    columns = ["target_api_record_id", "source_api_record_id", "date", "peer_n", "peer_median", "relative", "valid"]
    actual = generated.copy()
    actual["date"] = actual.source_trial_date.astype("string")
    actual["peer_n"] = pd.to_numeric(actual.peer_positive_time_n, errors="raise").astype("int64")
    actual["peer_median"] = pd.to_numeric(actual.peer_median_time_seconds, errors="coerce")
    actual["relative"] = pd.to_numeric(actual.relative_time, errors="coerce")
    actual["valid"] = actual.relative.notna()
    actual = actual[columns].sort_values(columns[:2], kind="stable").reset_index(drop=True)
    reference = expected[columns].copy().sort_values(columns[:2], kind="stable").reset_index(drop=True)
    if not actual[columns[:2]].astype("int64").equals(reference[columns[:2]].astype("int64")):
        raise AssertionError("selected trial slot target/source IDs differ from root reference")
    if len(actual) != 19:
        raise AssertionError(f"expected 19 target trial slots, found {len(actual)}")
    if not actual.date.astype("string").equals(reference.date.astype("string")):
        raise AssertionError("selected trial slot dates differ from root reference")
    if not actual.peer_n.astype("int64").equals(reference.peer_n.astype("int64")):
        raise AssertionError("selected trial slot peer counts differ from root reference")
    for column in ("peer_median", "relative"):
        a = pd.to_numeric(actual[column], errors="coerce").to_numpy(dtype="float64", na_value=np.nan)
        b = pd.to_numeric(reference[column], errors="coerce").to_numpy(dtype="float64", na_value=np.nan)
        if not np.allclose(a, b, rtol=0, atol=1e-12, equal_nan=True):
            raise AssertionError(f"selected trial slot {column} differs from root reference")
    if not actual.valid.astype(bool).equals(reference.valid.astype(bool)):
        raise AssertionError("selected trial slot validity differs from root reference")
    return {"rows": len(actual), "all_slots_exact_within_1e-12": True}


def main() -> dict:
    outputs = (OUT_FEATURES, OUT_SLOTS, OUT_RECEIPT)
    if any(path.exists() for path in outputs):
        raise FileExistsError("refusing to overwrite a fresh trial4 dry-run artifact")

    if sha256(SOURCE_MANIFEST) != SOURCE_MANIFEST_SHA256:
        raise AssertionError("frozen source manifest changed")
    if sha256(TRIAL_SOURCE) != TRIAL_SOURCE_SHA256:
        raise AssertionError("frozen API20 peer source changed")

    core = load_module("fresh_period_frozen_feature_core", FEATURE_CORE)
    base_columns = ["api_record_id", "race_id", "race_date", "history_cutoff", "horse_id", *BASE_FEATURES]
    baseline = pd.read_parquet(BASE30_PATH, columns=base_columns)
    baseline["api_record_id"] = pd.to_numeric(baseline.api_record_id, errors="raise").astype("int64")
    if len(baseline) != 426 or baseline.api_record_id.duplicated().any():
        raise AssertionError("fresh F1 baseline inputs must be 426 unique target rows")

    target_columns = [
        "api_record_id", "race_id", "race_date", "horse_id", "history_cutoff",
        "target_api_record_id", "frozen_started_n", "cold_under_frozen_snapshot",
        "race_distance_m",
    ]
    cold = pd.read_parquet(TARGET_SOURCE, columns=target_columns)
    cold["api_record_id"] = pd.to_numeric(cold.api_record_id, errors="raise").astype("int64")
    cold["target_api_record_id"] = pd.to_numeric(cold.target_api_record_id, errors="raise").astype("int64")
    cold["frozen_started_n"] = pd.to_numeric(cold.frozen_started_n, errors="raise").astype("int64")
    cold["cold_under_frozen_snapshot"] = strict_bool(cold.cold_under_frozen_snapshot, "cold_under_frozen_snapshot")
    if len(cold) != 14 or cold.api_record_id.duplicated().any():
        raise AssertionError("source-frozen cold roster must contain 14 unique target rows")
    if not cold.api_record_id.equals(cold.target_api_record_id):
        raise AssertionError("target IDs must match exact API4 source-row IDs")
    if not cold.frozen_started_n.eq(0).all() or not cold.cold_under_frozen_snapshot.all():
        raise AssertionError("cold target definition differs from the frozen started-history snapshot")
    if not pd.to_numeric(cold.race_distance_m, errors="raise").eq(900).all():
        raise AssertionError("fresh cold subset distance scope changed")
    target_roster = cold[["api_record_id", "race_id", "race_date", "history_cutoff", "horse_id"]].copy()
    target_roster["observed_starts"] = cold.frozen_started_n.to_numpy(dtype="int64")

    peers = pd.read_parquet(TRIAL_SOURCE)
    normalized_trials = normalize_trial_rows(peers)
    result, ledger = core.add_features(baseline, target_roster, normalized_trials)

    expected4 = pd.read_parquet(ROOT_TRIAL4, columns=["api_record_id", *TRIAL_FEATURES])
    trial4_comparison = compare_features(
        result.loc[result.api_record_id.isin(set(cold.api_record_id)), ["api_record_id", *TRIAL_FEATURES]],
        expected4,
        TRIAL_FEATURES,
        "14-row frozen trial4 comparison",
    )

    expected30 = pd.read_parquet(ROOT_BASE30, columns=["api_record_id", *BASE_FEATURES])
    base30_comparison = compare_features(
        result[["api_record_id", *BASE_FEATURES]], expected30, BASE_FEATURES,
        "426-row root base30 comparison",
    )
    expected34 = pd.read_parquet(ROOT_INPUT34, columns=["api_record_id", *MODEL_FEATURES])
    features = result[["api_record_id", "race_id", "race_date", "horse_id", *MODEL_FEATURES]].copy()
    input34_comparison = compare_features(
        features[["api_record_id", *MODEL_FEATURES]], expected34,
        MODEL_FEATURES, "426-row frozen 34-input comparison",
    )

    slots_reference = pd.read_parquet(ROOT_TRIAL_SLOTS)
    slot_comparison = compare_trial_slots(ledger, slots_reference)
    if len(ledger) != 19:
        raise AssertionError(f"expected 19 generated selected-event slots, found {len(ledger)}")

    # Verify core's frozen behavior for rows outside the no-start roster. Only
    # the four feature columns are checked; no outcomes are read or joined.
    experienced_ids = set(baseline.loc[pd.to_numeric(baseline.observed_starts, errors="raise").gt(0), "api_record_id"])
    if result.loc[result.api_record_id.isin(experienced_ids), TRIAL_FEATURES].notna().any().any():
        raise AssertionError("experienced runner rows must retain NULL trial4 inputs")

    # The final feature table deliberately contains no finish/result labels,
    # race outcomes, source payloads, or labels from the source roster.
    output_columns = ["api_record_id", "race_id", "race_date", "horse_id", *MODEL_FEATURES]
    final_features = features[output_columns].copy()
    if "finish_position" in final_features.columns or len(final_features.columns) != 38:
        raise AssertionError("final artifact must contain identifiers and exactly 34 model inputs, without outcomes")
    slot_columns = [
        "target_api_record_id", "target_race_id", "target_race_date", "target_cutoff",
        "target_horse_id", "slot_oldest_to_newest", "slot_rank_desc", "source_api_record_id",
        "source_trial_event_key", "source_trial_event_order", "source_trial_date", "source_day_serial",
        "source_horse_id", "source_time_seconds", "source_ord_raw", "source_judgment_raw",
        "source_time_ineligible_reasons", "source_time_eligible", "peer_positive_time_n",
        "peer_median_time_seconds", "peer_api_record_ids_json", "peer_horse_ids_json",
        "relative_time", "ineligible_reason",
    ]
    final_slots = ledger[slot_columns].copy()

    receipt = {
        "status": "frozen_trial4_feature_preflight_passed_no_scoring",
        "database_opened": False,
        "predictions_computed": False,
        "outcome_metrics_computed": False,
        "model_fit_or_calibration_calls": 0,
        "root_scoring_release_received": False,
        "trial4_builder_loaded_outcomes": False,
        "upstream_f1_dryrun_artifact_contains_fresh_result_fields": True,
        "frozen_cohort_eligibility_uses_fresh_result_fields": True,
        "pre_release_score_pairing_or_performance_metrics_computed": False,
        "preflight_data_use_note": (
            "The upstream F1 feature dry-run frame carries finish_position from the fresh source, and the frozen "
            "cohort-quality contract uses result/status fields. This trial4 feature builder reads only non-label "
            "columns; no fresh scores were paired with outcomes and no performance metrics were computed before release."
        ),
        "scope": {
            "eligible_feature_rows": 426,
            "eligible_races": 45,
            "cold_target_rows": 14,
            "cold_unique_horses": int(cold.horse_id.nunique()),
            "cold_races": int(cold.race_id.nunique()),
            "cold_dates": sorted(cold.race_date.astype(str).unique().tolist()),
            "cold_distance_m": sorted(pd.to_numeric(cold.race_distance_m, errors="raise").unique().astype(int).tolist()),
            "audited_api20_full_peer_rows": len(peers),
            "linked_trial_events": int(normalized_trials.trial_event_key.nunique()),
            "generated_selected_event_slots": int(len(ledger)),
        },
        "checks": {
            "frozen_source_manifest_sha256": SOURCE_MANIFEST_SHA256,
            "frozen_api20_source_sha256": TRIAL_SOURCE_SHA256,
            "base30_reference": base30_comparison,
            "trial4_14_row_reference": trial4_comparison,
            "frozen_34_input_reference": input34_comparison,
            "selected_trial_slots_reference": slot_comparison,
            "cold_trial4_input_rows": int(result.api_record_id.isin(set(cold.api_record_id)).sum()),
            "experienced_trial4_values_all_null": True,
            "model_input_feature_count": int(len(MODEL_FEATURES)),
        },
        "input_sha256": {
            "fresh_30_builder_output": sha256(BASE30_PATH),
            "frozen_source_manifest": sha256(SOURCE_MANIFEST),
            "api20_full_peer_event_rows": sha256(TRIAL_SOURCE),
            "source_cold_target_roster": sha256(TARGET_SOURCE),
            "frozen_feature_core": sha256(FEATURE_CORE),
            "root_base30_reference": sha256(ROOT_BASE30),
            "root_input34_reference": sha256(ROOT_INPUT34),
            "root_trial4_reference": sha256(ROOT_TRIAL4),
            "root_trial_slot_reference": sha256(ROOT_TRIAL_SLOTS),
        },
    }

    final_features.to_parquet(OUT_FEATURES, index=False)
    final_slots.to_parquet(OUT_SLOTS, index=False)
    receipt["output_sha256"] = {
        OUT_FEATURES.name: sha256(OUT_FEATURES),
        OUT_SLOTS.name: sha256(OUT_SLOTS),
    }
    receipt["passed"] = True
    OUT_RECEIPT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return receipt


if __name__ == "__main__":
    print(json.dumps(main(), ensure_ascii=False, indent=2))
