"""Synthetic-only checks for the audited three-feature input contract."""
from __future__ import annotations

import numpy as np
import pandas as pd

from entry_input_contract import (
    FEATURE_COLUMNS,
    LATEST_PRIOR_MISSING_STATUSES,
    LATEST_PRIOR_STATUS_VALUES,
    LATEST_PRIOR_VALID_START_CLASSES,
    LATEST_PRIOR_VALID_STATUSES,
    NUMBER_FRACTION_FORMULA,
    NUMBER_DENOMINATOR_RULE,
    PREVIOUS_WEIGHT_SELECTION_RULE,
    PREVIOUS_WEIGHT_SOURCE_TYPE,
    PREVIOUS_WEIGHT_VALIDITY_RULE,
    PREVIOUS_WEIGHT_RULE,
    validate_audited_inputs,
)


def _contract() -> dict[str, object]:
    return {
        "weight_unit": "kg",
        "previous_weight_rule": PREVIOUS_WEIGHT_RULE,
        "previous_weight_source_type": PREVIOUS_WEIGHT_SOURCE_TYPE,
        "latest_prior_selection_rule": PREVIOUS_WEIGHT_SELECTION_RULE,
        "latest_prior_validity_rule": PREVIOUS_WEIGHT_VALIDITY_RULE,
        "latest_prior_valid_statuses": list(LATEST_PRIOR_VALID_STATUSES),
        "latest_prior_missing_statuses": list(LATEST_PRIOR_MISSING_STATUSES),
        "latest_prior_status_values": list(LATEST_PRIOR_STATUS_VALUES),
        "latest_prior_valid_start_classes": list(LATEST_PRIOR_VALID_START_CLASSES),
        "number_fraction_formula": NUMBER_FRACTION_FORMULA,
        "number_denominator_rule": NUMBER_DENOMINATOR_RULE,
        "max_number_column": "max_declared_horse_number",
        "full_card_roster_confirmed_statuses": ["full_card_roster_exact"],
        "full_card_roster_status_values": ["full_card_roster_exact", "unconfirmed"],
        "full_card_roster_reason_values": [
            "exact_full_card_official_roster_match", "official_roster_id_name_or_distance_mismatch",
            "no_exact_full_card_source_roster",
        ],
        "number_denominator_source_statuses": ["full_card_roster_exact"],
        "feature_columns": list(FEATURE_COLUMNS),
        "current_weight_source_type": "dacom01_h3_dated_declaration",
        "publication_time_status": "assumed_from_declaration_date_publication_unverified",
        "pre_race_availability_verified": False,
        "pre_race_availability_assumption": True,
    }


def _frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    target = pd.DataFrame([
        {"api_record_id": 1101, "race_id": "2024-05-10_2_1", "race_date": "2024-05-10", "horse_id": "h1",
         "horse_number": 1, "field_n": 4},
        {"api_record_id": 1102, "race_id": "2024-05-10_2_1", "race_date": "2024-05-10", "horse_id": "h2",
         "horse_number": 2, "field_n": 4},
        {"api_record_id": 1103, "race_id": "2024-05-10_2_1", "race_date": "2024-05-10", "horse_id": "h3",
         "horse_number": 3, "field_n": 4},
        {"api_record_id": 1104, "race_id": "2024-05-10_2_1", "race_date": "2024-05-10", "horse_id": "h4",
         "horse_number": 4, "field_n": 4},
    ])
    audit = target.copy()
    audit["entry_id"] = ["e1", "e2", "e3", "e4"]
    audit["event_number"] = 1
    audit["source_event_number"] = 1
    audit["declared_horse_number"] = [1, 2, 3, np.nan]
    audit["max_declared_horse_number"] = 4
    audit["max_full_card_declared_horse_number"] = 4
    audit["full_card_roster_confirmed"] = True
    audit["full_card_roster_status"] = "full_card_roster_exact"
    audit["full_card_roster_reason"] = "exact_full_card_official_roster_match"
    audit["max_declared_horse_number_source_document_id"] = "full-doc-1"
    audit["max_declared_horse_number_source_file_date"] = "2024-05-08"
    audit["max_declared_horse_number_source_document_sha256"] = "e" * 64
    audit["max_declared_horse_number_source_status"] = "full_card_roster_exact"
    audit["current_declared_burden_kg"] = [57.0, np.nan, 55.0, 50.0]
    audit["burden_change_vs_last_valid_kg"] = [1.0, np.nan, np.nan, 1.0]
    audit["horse_number_fraction"] = [0.0, 1.0 / 3.0, 2.0 / 3.0, np.nan]
    audit["latest_prior_burden_kg"] = [56.0, 54.0, np.nan, 49.0]
    audit["latest_prior_race_date"] = ["2024-05-08", "2024-05-08", None, "2024-05-08"]
    audit["latest_prior_race_id"] = ["prior1", "prior2", None, "prior4"]
    audit["latest_prior_horse_id"] = ["h1", "h2", None, "h4"]
    audit["latest_prior_source_row_id"] = [101, 102, None, 104]
    audit["latest_prior_source_row_sha256"] = ["a" * 64, "a" * 64, None, "a" * 64]
    audit["latest_prior_source_artifact_id"] = ["db1", "db1", None, "db1"]
    audit["latest_prior_source_artifact_path"] = ["data/history.db", "data/history.db", None, "data/history.db"]
    audit["latest_prior_source_artifact_sha256"] = ["b" * 64, "b" * 64, None, "b" * 64]
    audit["latest_prior_source_line_number"] = [1, 2, np.nan, 4]
    audit["latest_prior_start_class"] = ["normal_completed", "actual_positive_time_observation", None,
                                         "actual_positive_time_observation"]
    audit["latest_prior_status"] = ["latest_valid_actual_burden", "latest_valid_actual_burden",
                                    "no_prior_valid_actual_burden", "latest_valid_actual_burden"]
    audit["latest_prior_cutoff"] = "2024-05-08"
    audit["latest_prior_fallback_after_ambiguous_special"] = False
    audit["prior_source_snapshot_complete"] = [True, True, True, True]
    audit["source_document_id"] = ["doc1", "doc2", "doc3", "doc4"]
    audit["source_file_date"] = ["2024-05-08", "2024-05-08", "2024-05-08", "2024-05-08"]
    audit["source_document_sha256"] = ["c" * 64, "c" * 64, "c" * 64, "c" * 64]
    audit["source_line_sha256"] = ["d" * 64, "d" * 64, "d" * 64, "d" * 64]
    audit["source_raw_horse_name"] = ["horse one", "horse two", "horse three", "★horse four"]
    audit["current_source_status"] = ["dacom01_exact_name_match", "dacom01_exact_name_match",
                                       "dacom01_exact_name_match", "dacom01_direct_single_star_marker_match"]
    audit["source_type"] = "dacom01_h3_dated_declaration"
    audit["publication_time_status"] = "assumed_from_declaration_date_publication_unverified"
    audit["burden_status"] = ["valid", "missing", "valid", "valid"]
    audit["number_status"] = ["valid", "valid", "valid", "missing_declaration_number"]
    return target, audit


def _must_fail(target: pd.DataFrame, audit: pd.DataFrame, contract: dict[str, object], phrase: str) -> None:
    try:
        validate_audited_inputs(target, audit, contract)
    except ValueError as error:
        assert phrase in str(error), str(error)
    else:
        raise AssertionError(f"invalid synthetic audit artifact accepted: {phrase}")


def run_tests() -> dict[str, object]:
    target, audit = _frames()
    model_inputs, receipt = validate_audited_inputs(target, audit, _contract())
    assert list(model_inputs.columns) == ["api_record_id", "race_id", *FEATURE_COLUMNS]
    assert len(model_inputs) == len(target) == 4 and model_inputs.api_record_id.is_unique
    assert all(model_inputs[column].dtype == np.dtype("float64") for column in FEATURE_COLUMNS)
    assert np.allclose(model_inputs.horse_number_fraction.iloc[:3], [0.0, 1.0 / 3.0, 2.0 / 3.0],
                       atol=1e-15, rtol=0.0)
    assert model_inputs.horse_number_fraction.isna().sum() == 1
    assert model_inputs.current_declared_burden_kg.isna().sum() == 1
    assert model_inputs.burden_change_vs_last_valid_kg.isna().sum() == 2
    assert receipt["rows"] == 4 and receipt["races"] == 1
    assert receipt["pre_race_availability_verified"] is False
    assert receipt["pre_race_availability_assumption"] is True
    assert receipt["declared_number_fraction_missing_rows"] == 1
    assert receipt["target_vs_full_card_declared_max_disagreement_races"] == 0

    bad_cutoff = audit.copy()
    bad_cutoff.loc[0, "latest_prior_race_date"] = "2024-05-09"
    _must_fail(target, bad_cutoff, _contract(), "T−2 date cutoff")

    bad_current_cutoff = audit.copy()
    bad_current_cutoff.loc[0, "source_file_date"] = "2024-05-09"
    _must_fail(target, bad_current_cutoff, _contract(), "fixed T−2 builder cutoff")

    bad_delta = audit.copy()
    bad_delta.loc[0, "burden_change_vs_last_valid_kg"] = 2.0
    _must_fail(target, bad_delta, _contract(), "current minus latest prior")

    incomplete_snapshot = audit.copy()
    incomplete_snapshot.loc[0, "prior_source_snapshot_complete"] = False
    incomplete_snapshot.loc[0, "latest_prior_status"] = \
        "latest_observed_through_snapshot_cutoff_not_complete_asof_T_minus_2"
    incomplete_snapshot.loc[0, "burden_change_vs_last_valid_kg"] = np.nan
    _, incomplete_receipt = validate_audited_inputs(target, incomplete_snapshot, _contract())
    assert incomplete_receipt["prior_source_snapshot_incomplete_rows"] == 1
    incomplete_with_delta = incomplete_snapshot.copy()
    incomplete_with_delta.loc[0, "burden_change_vs_last_valid_kg"] = 1.0
    _must_fail(target, incomplete_with_delta, _contract(), "without current/prior values or a complete prior snapshot")

    bad_fraction = audit.copy()
    bad_fraction.loc[1, "horse_number_fraction"] = 0.25
    _must_fail(target, bad_fraction, _contract(), "fixed formula")

    bad_fullcard_max = audit.copy()
    bad_fullcard_max["max_full_card_declared_horse_number"] = 5
    _must_fail(target, bad_fullcard_max, _contract(), "full-card maximum must equal the S40 roster maximum")

    bad_missing_fraction = audit.copy()
    bad_missing_fraction.loc[3, "horse_number_fraction"] = 0.0
    _must_fail(target, bad_missing_fraction, _contract(), "fixed formula")

    bad_horse = audit.copy()
    bad_horse.loc[0, "latest_prior_horse_id"] = "different-horse"
    _must_fail(target, bad_horse, _contract(), "same official horse ID")

    stray_prior_lineage = audit.copy()
    stray_prior_lineage.loc[2, "latest_prior_source_row_id"] = 999
    _must_fail(target, stray_prior_lineage, _contract(), "stray actual-result lineage")

    bad_source = audit.copy()
    bad_source["source_type"] = "result_recorded_weight_proxy"
    _must_fail(target, bad_source, _contract(), "row source_type")

    result_contract = {
        **_contract(),
        "current_weight_source_type": "result_recorded_weight_proxy",
        "publication_time_status": "unknown",
        "pre_race_availability_assumption": False,
    }
    _must_fail(target, audit, result_contract, "current weight must use the audited H3 declaration source")

    bad_star_proof = audit.copy()
    bad_star_proof.loc[3, "source_raw_horse_name"] = "horse four"
    _must_fail(target, bad_star_proof, _contract(), "exact raw marker/name")

    duplicate_natural_key = audit.copy()
    duplicate_natural_key.loc[1, "event_number"] = 2
    _must_fail(target, duplicate_natural_key, _contract(), "source event_number does not match")

    bad_source_event_number = audit.copy()
    bad_source_event_number.loc[0, "source_event_number"] = 2
    _must_fail(target, bad_source_event_number, _contract(), "matched H3 source_event_number")

    unconfirmed_denominator = audit.copy()
    unconfirmed_denominator.loc[0, "full_card_roster_confirmed"] = False
    _must_fail(target, unconfirmed_denominator, _contract(), "requires a confirmed full declaration roster")

    no_fullcard_proof = audit.copy()
    no_fullcard_proof["full_card_roster_confirmed"] = False
    no_fullcard_proof["full_card_roster_status"] = "unconfirmed"
    no_fullcard_proof["full_card_roster_reason"] = "no_exact_full_card_source_roster"
    no_fullcard_proof["max_declared_horse_number"] = np.nan
    no_fullcard_proof["max_full_card_declared_horse_number"] = np.nan
    no_fullcard_proof["horse_number_fraction"] = np.nan
    for column in ("max_declared_horse_number_source_document_id",
                   "max_declared_horse_number_source_file_date",
                   "max_declared_horse_number_source_document_sha256"):
        no_fullcard_proof[column] = None
    no_fullcard_proof["max_declared_horse_number_source_status"] = "unconfirmed"
    unconfirmed_model_inputs, unconfirmed_receipt = validate_audited_inputs(
        target, no_fullcard_proof, _contract())
    assert unconfirmed_model_inputs.horse_number_fraction.isna().all()
    assert unconfirmed_receipt["full_card_roster_confirmed_rows"] == 0

    missing_target = target.iloc[:-1].copy()
    _must_fail(missing_target, audit, _contract(), "exact frozen S40 target keys")

    single_target = target.iloc[:1].copy()
    single_target["field_n"] = 1
    single_audit = audit.iloc[:1].copy()
    single_audit["field_n"] = 1
    single_audit["declared_horse_number"] = 1
    single_audit["max_declared_horse_number"] = 1
    single_audit["max_full_card_declared_horse_number"] = 1
    single_audit["max_declared_horse_number_source_file_date"] = "2024-05-08"
    single_audit["horse_number_fraction"] = np.nan
    single_audit["burden_change_vs_last_valid_kg"] = np.nan
    single_audit["latest_prior_burden_kg"] = np.nan
    single_audit["latest_prior_race_date"] = None
    single_audit["latest_prior_race_id"] = None
    single_audit["latest_prior_horse_id"] = None
    single_audit["latest_prior_start_class"] = None
    single_audit["latest_prior_status"] = "no_prior_valid_actual_burden"
    single_audit["latest_prior_cutoff"] = "2024-05-08"
    single_audit["latest_prior_fallback_after_ambiguous_special"] = False
    for column in ("latest_prior_race_date", "latest_prior_source_row_id", "latest_prior_source_row_sha256",
                   "latest_prior_source_artifact_id", "latest_prior_source_artifact_path",
                   "latest_prior_source_artifact_sha256", "latest_prior_source_line_number",
                   "latest_prior_start_class"):
        single_audit[column] = None
    _, single_receipt = validate_audited_inputs(single_target, single_audit, _contract())
    assert single_receipt["declared_number_fraction_missing_rows"] == 1

    # OOS score `year` is the model vintage; race_date is the event year.
    from entry_pipeline import validate_oos_score_vintages
    score_rows = pd.DataFrame([
        {"arm": "E", "year": 2025, "role": "calibration", "api_record_id": 1, "race_date": "2024-05-01"},
        {"arm": "E", "year": 2025, "role": "calibration", "api_record_id": 2, "race_date": "2024-05-02"},
        {"arm": "E", "year": 2025, "role": "evaluation", "api_record_id": 3, "race_date": "2025-05-01"},
        {"arm": "E", "year": 2025, "role": "evaluation", "api_record_id": 4, "race_date": "2025-05-02"},
    ])
    validate_oos_score_vintages(score_rows, "E", {2025: 2}, {2025: 2})
    wrong_calibration_vintage = score_rows.copy()
    wrong_calibration_vintage.loc[0, "year"] = 2024
    try:
        validate_oos_score_vintages(wrong_calibration_vintage, "E", {2025: 2}, {2025: 2})
    except RuntimeError as error:
        assert "year values do not identify model vintages" in str(error) or \
               "role dates do not match" in str(error), str(error)
    else:
        raise AssertionError("calibration event year was accepted as the model vintage")

    return {
        "status": "PASS_SYNTHETIC",
        "fit_calls": 0,
        "source_rows_read": 0,
        "candidate_probabilities_or_outcomes": False,
        "checks": [
            "exact three numeric features and frozen target key coverage",
            "declared horse-number formula uses the source-confirmed maximum for the S40 target roster",
            "missing declared number and denominator <= 1 preserve a NULL fraction and target row",
            "target/result horse number and full-card declaration maximum stay distinct audit fields",
            "current-minus-prior burden delta and missingness preservation",
            "same-official-horse T−2 lineage and prior-source provenance",
            "H3 declaration provenance and publication-time assumption stay distinct",
            "calibration/evaluation score rows store model vintage separately from event year",
            "event/horse source key and race-key consistency checks",
            "invalid date, delta, fraction, horse key, source type, and row coverage fail closed",
        ],
    }
