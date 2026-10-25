"""Validate the audited S43 input without reopening source rows or deriving features.

The source-audit owner creates the small feature/lineage artifact. This module
only checks its contract and returns the exact three model columns; it performs
no file, database, network, feature-generation, fitting, or evaluation work.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd


FEATURE_COLUMNS = (
    "current_declared_burden_kg",
    "burden_change_vs_last_valid_kg",
    "horse_number_fraction",
)
TARGET_KEYS = ("api_record_id", "race_id", "race_date", "horse_id", "horse_number", "field_n")
LINEAGE_COLUMNS = (
    "entry_id",
    "event_number",
    "source_event_number",
    "declared_horse_number",
    "max_declared_horse_number",
    "max_full_card_declared_horse_number",
    "full_card_roster_confirmed",
    "full_card_roster_status",
    "full_card_roster_reason",
    "max_declared_horse_number_source_document_id",
    "max_declared_horse_number_source_file_date",
    "max_declared_horse_number_source_document_sha256",
    "max_declared_horse_number_source_status",
    "latest_prior_burden_kg",
    "latest_prior_race_date",
    "latest_prior_race_id",
    "latest_prior_horse_id",
    "latest_prior_source_row_id",
    "latest_prior_source_row_sha256",
    "latest_prior_source_artifact_id",
    "latest_prior_source_artifact_path",
    "latest_prior_source_artifact_sha256",
    "latest_prior_source_line_number",
    "latest_prior_start_class",
    "latest_prior_status",
    "latest_prior_cutoff",
    "latest_prior_fallback_after_ambiguous_special",
    "prior_source_snapshot_complete",
    "source_document_id",
    "source_file_date",
    "source_document_sha256",
    "source_line_sha256",
    "source_raw_horse_name",
    "current_source_status",
    "source_type",
    "publication_time_status",
    "burden_status",
    "number_status",
)
PREVIOUS_WEIGHT_RULE = (
    "same_official_horse_id; actual past race row; "
    "event_race_date <= target_race_date_minus_2_calendar_days_inclusive; "
    "latest eligible valid burden"
)
NUMBER_FRACTION_FORMULA = "(declared_horse_number - 1) / (max_declared_horse_number - 1)"
NUMBER_DENOMINATOR_RULE = (
    "max_declared_horse_number is the confirmed maximum declared horse number from the original "
    "full declaration roster matching the exact S40 target roster; never the maximum of only "
    "observed H3 feature rows"
)
PREVIOUS_WEIGHT_SOURCE_TYPE = (
    "api4_native_result_source_row.normalized_json.$.wgBudam_actual_carried_weight"
)
PREVIOUS_WEIGHT_SELECTION_RULE = (
    "maximum eligible event date <= T−2 inclusive; unique horse/day required; "
    "deterministic event_number/source_row_id order; duplicates rejected"
)
PREVIOUS_WEIGHT_VALIDITY_RULE = (
    "raw ord == finish_position; burden 30..100 kg; normal_completed ord 1..89 with positive "
    "finish_time_ms; ord 91/92 require raw rcTime>0 and positive finish_time_ms and are labeled "
    "actual_positive_time_observation without ordinal semantics"
)
LATEST_PRIOR_VALID_STATUSES = (
    "latest_valid_actual_burden",
    "fallback_after_ambiguous_special_92",
    "latest_observed_through_snapshot_cutoff_not_complete_asof_T_minus_2",
)
LATEST_PRIOR_MISSING_STATUSES = (
    "no_prior_valid_actual_burden",
    "no_prior_valid_actual_after_ambiguous_special",
    "source_snapshot_truncated_before_cutoff_no_observed_prior",
)
LATEST_PRIOR_STATUS_VALUES = LATEST_PRIOR_VALID_STATUSES + LATEST_PRIOR_MISSING_STATUSES
LATEST_PRIOR_VALID_START_CLASSES = ("normal_completed", "actual_positive_time_observation")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _date_strings(values: pd.Series, name: str, *, allow_missing: bool = False) -> pd.Series:
    parsed = pd.to_datetime(values, errors="coerce")
    if allow_missing:
        _require((values.isna() | parsed.notna()).all(), f"invalid {name} date")
    else:
        _require(parsed.notna().all(), f"invalid {name} date")
    return parsed.dt.strftime("%Y-%m-%d")


def _integer_values(values: pd.Series, name: str) -> np.ndarray:
    numeric = pd.to_numeric(values, errors="coerce").to_numpy(dtype=np.float64)
    _require(np.isfinite(numeric).all() and np.equal(numeric, np.rint(numeric)).all() and
             (numeric > 0).all(), f"{name} must contain positive exact integers")
    return numeric.astype(np.int64)


def _numeric_or_missing(values: pd.Series, name: str) -> np.ndarray:
    numeric = pd.to_numeric(values, errors="coerce").to_numpy(dtype=np.float64)
    _require((np.isfinite(numeric) | np.isnan(numeric)).all(), f"{name} contains non-finite values")
    return numeric


def validate_audited_inputs(
    target_rows: pd.DataFrame,
    audit_features: pd.DataFrame,
    source_contract: Mapping[str, Any],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Check the audited three-feature artifact against the frozen S40 roster.

    ``audit_features`` is already produced by the source-audit role. Its
    non-feature fields are used only for verification and never returned in
    the model matrix. Target rows remain one-to-one, including rows with
    missing burdens.
    """
    _require(source_contract.get("weight_unit") == "kg", "audited source contract does not confirm kg units")
    _require(source_contract.get("previous_weight_rule") == PREVIOUS_WEIGHT_RULE,
             "audited previous-weight rule differs from the fixed T−2 rule")
    _require(source_contract.get("previous_weight_source_type") == PREVIOUS_WEIGHT_SOURCE_TYPE,
             "audited previous-weight source differs from the API4 actual-result field")
    _require(source_contract.get("latest_prior_selection_rule") == PREVIOUS_WEIGHT_SELECTION_RULE,
             "audited previous-weight selection rule differs from the latest eligible actual row rule")
    _require(source_contract.get("latest_prior_validity_rule") == PREVIOUS_WEIGHT_VALIDITY_RULE,
             "audited previous-weight validity rule differs from the fixed actual-start rule")
    for field, expected in (
        ("latest_prior_valid_statuses", LATEST_PRIOR_VALID_STATUSES),
        ("latest_prior_missing_statuses", LATEST_PRIOR_MISSING_STATUSES),
        ("latest_prior_status_values", LATEST_PRIOR_STATUS_VALUES),
        ("latest_prior_valid_start_classes", LATEST_PRIOR_VALID_START_CLASSES),
    ):
        actual = source_contract.get(field)
        _require(isinstance(actual, list) and len(actual) == len(expected) and
                 set(actual) == set(expected),
                 f"audited {field} differs from the frozen prior-row eligibility statuses")
    _require(source_contract.get("number_fraction_formula") == NUMBER_FRACTION_FORMULA,
             "audited entry-number formula differs from the fixed normalized fraction")
    _require(source_contract.get("number_denominator_rule") == NUMBER_DENOMINATOR_RULE,
             "audited entry-number denominator rule differs from the fixed full-roster rule")
    _require(source_contract.get("max_number_column") == "max_declared_horse_number",
             "audited number denominator is not pinned")
    _require(source_contract.get("feature_columns") == list(FEATURE_COLUMNS),
             "audited input must contain exactly the three contracted feature columns")
    expected_source_type = source_contract.get("current_weight_source_type")
    expected_publication_status = source_contract.get("publication_time_status")
    _require(isinstance(expected_source_type, str) and bool(expected_source_type),
             "audited current-weight source type is missing")
    _require(isinstance(expected_publication_status, str) and bool(expected_publication_status),
             "audited publication-time status is missing")
    availability_verified = source_contract.get("pre_race_availability_verified")
    availability_assumption = source_contract.get("pre_race_availability_assumption")
    _require(type(availability_verified) is bool and type(availability_assumption) is bool,
             "source contract must separate verified publication from an availability assumption")
    if expected_source_type == "dacom01_h3_dated_declaration":
        _require(expected_publication_status == "assumed_from_declaration_date_publication_unverified" and
                 not availability_verified and availability_assumption,
                 "H3 dated declarations must carry the separate publication-date assumption")
    else:
        _require(False, "current weight must use the audited H3 declaration source; proxy fallback is prohibited")

    required_target = set(TARGET_KEYS)
    required_audit = required_target | set(FEATURE_COLUMNS) | set(LINEAGE_COLUMNS)
    _require(required_target.issubset(target_rows.columns), "frozen S40 target key schema is incomplete")
    _require(required_audit.issubset(audit_features.columns), "audited feature/lineage schema is incomplete")
    _require(not target_rows.empty, "frozen S40 target roster is empty")

    target = target_rows.loc[:, list(TARGET_KEYS)].copy()
    audit = audit_features.loc[:, [*TARGET_KEYS, *FEATURE_COLUMNS, *LINEAGE_COLUMNS]].copy()
    _require(target.api_record_id.notna().all() and target.api_record_id.is_unique,
             "target API record keys must be complete and unique")
    _require(audit.api_record_id.notna().all() and audit.api_record_id.is_unique,
             "audited API record keys must be complete and unique")
    for frame, date_column in ((target, "race_date"), (audit, "race_date")):
        frame[date_column] = _date_strings(frame[date_column], date_column)
    audit["latest_prior_race_date"] = _date_strings(audit.latest_prior_race_date,
                                                      "latest_prior_race_date", allow_missing=True)
    audit["latest_prior_cutoff"] = _date_strings(audit.latest_prior_cutoff,
                                                   "latest_prior_cutoff", allow_missing=True)
    audit["source_file_date"] = _date_strings(audit.source_file_date,
                                                "source_file_date", allow_missing=True)
    audit["max_declared_horse_number_source_file_date"] = _date_strings(
        audit.max_declared_horse_number_source_file_date,
        "max_declared_horse_number_source_file_date", allow_missing=True)
    for frame in (target, audit):
        frame["api_record_id"] = _integer_values(frame.api_record_id, "api_record_id")
        frame["horse_number"] = _integer_values(frame.horse_number, "horse_number")
        frame["field_n"] = _integer_values(frame.field_n, "field_n")
    for frame in (target, audit):
        _require(frame.race_id.map(lambda value: isinstance(value, str) and bool(value)).all() and
                 frame.horse_id.map(lambda value: isinstance(value, str) and bool(value)).all(),
                 "race/official horse IDs must be non-empty strings")
    _require(audit.event_number.notna().all(), "source event_number race keys must be complete")
    event_number = pd.to_numeric(audit.event_number, errors="coerce").to_numpy(dtype=np.float64)
    _require(np.isfinite(event_number).all() and np.equal(event_number, np.rint(event_number)).all() and
             (event_number > 0).all(), "event_number must be a positive exact race-key integer")
    target_event_number = pd.to_numeric(audit.race_id.astype(str).str.rsplit("_", n=1).str[-1],
                                        errors="coerce").to_numpy(dtype=np.float64)
    _require(np.isfinite(target_event_number).all() and np.array_equal(target_event_number, event_number),
             "source event_number does not match the trailing S40 race-key component")
    source_event_number = _numeric_or_missing(audit.source_event_number, "source_event_number")
    entry_id_present = audit.entry_id.notna()
    matched_source_event = entry_id_present.to_numpy()
    known_source_event = np.isfinite(source_event_number)
    _require(np.equal(source_event_number[known_source_event],
                      np.rint(source_event_number[known_source_event])).all() and
             (source_event_number[known_source_event] > 0).all(),
             "source_event_number must be a positive exact integer or missing")
    _require(np.array_equal(known_source_event, matched_source_event) and
             np.array_equal(source_event_number[matched_source_event],
                            event_number[matched_source_event]),
             "matched H3 source_event_number differs from the target race key or is missing")
    _require(audit.loc[entry_id_present, "entry_id"].astype(str).map(bool).all(),
             "matched source entry_id keys must be non-empty")
    _require(not audit.loc[entry_id_present, "entry_id"].astype(str).duplicated().any(),
             "matched source entry_id is not one-to-one")
    _require(not audit.loc[entry_id_present].duplicated(["race_id", "source_event_number", "horse_id"]).any(),
             "matched source event/horse natural key is not one-to-one")

    join = target.merge(audit.loc[:, list(TARGET_KEYS)], on="api_record_id", how="outer",
                        suffixes=("_target", "_audit"), validate="one_to_one", indicator=True)
    _require(len(join) == len(target) == len(audit) and join._merge.eq("both").all(),
             "audit feature rows do not cover the exact frozen S40 target keys")
    for column in TARGET_KEYS[1:]:
        _require(join[f"{column}_target"].eq(join[f"{column}_audit"]).all(),
                 f"audited {column} differs from frozen S40 key")
    _require((audit.groupby("race_id", sort=False).field_n.nunique() == 1).all(),
             "field_n changes within a race")
    race_sizes = audit.groupby("race_id", sort=False).size()
    race_fields = audit.groupby("race_id", sort=False).field_n.first()
    _require(race_sizes.eq(race_fields).all(), "audited target row count differs from field_n")
    declared_number = _numeric_or_missing(audit.declared_horse_number, "declared_horse_number")
    max_declared_number = _numeric_or_missing(audit.max_declared_horse_number,
                                               "max_declared_horse_number")
    full_card_max = _numeric_or_missing(audit.max_full_card_declared_horse_number,
                                         "max_full_card_declared_horse_number")
    for values, name in ((declared_number, "declared_horse_number"),
                         (max_declared_number, "max_declared_horse_number"),
                         (full_card_max, "max_full_card_declared_horse_number")):
        known = np.isfinite(values)
        _require(np.equal(values[known], np.rint(values[known])).all() and (values[known] > 0).all(),
                 f"{name} must be a positive exact integer or missing")
    roster_confirmed_series = audit.full_card_roster_confirmed
    _require(roster_confirmed_series.notna().all() and
             roster_confirmed_series.map(lambda value: isinstance(value, (bool, np.bool_))).all(),
             "full declaration roster confirmation must be explicit boolean per target row")
    roster_confirmed = roster_confirmed_series.to_numpy(dtype=bool)
    denominator_present = np.isfinite(max_declared_number)
    _require(np.array_equal(denominator_present, roster_confirmed),
             "a non-null entry-number denominator requires a confirmed full declaration roster")
    _require(audit.full_card_roster_status.notna().all() and
             audit.full_card_roster_reason.notna().all() and
             audit.full_card_roster_status.astype(str).map(bool).all() and
             audit.full_card_roster_reason.astype(str).map(bool).all(),
             "full declaration roster status/reason lineage must be explicit")
    confirmed_roster_statuses = source_contract.get("full_card_roster_confirmed_statuses")
    roster_status_values = source_contract.get("full_card_roster_status_values")
    roster_reason_values = source_contract.get("full_card_roster_reason_values")
    denominator_source_statuses = source_contract.get("number_denominator_source_statuses")
    _require(isinstance(confirmed_roster_statuses, list) and confirmed_roster_statuses and
             all(isinstance(item, str) and item for item in confirmed_roster_statuses),
             "source contract must enumerate confirmed full-roster statuses")
    _require(isinstance(roster_status_values, list) and roster_status_values and
             all(isinstance(item, str) and item for item in roster_status_values) and
             set(confirmed_roster_statuses).issubset(set(roster_status_values)),
             "source contract must enumerate all full-roster statuses")
    _require(set(roster_status_values) == {"full_card_roster_exact", "unconfirmed"} and
             set(confirmed_roster_statuses) == {"full_card_roster_exact"},
             "full-card roster status vocabulary differs from the fixed audited states")
    _require(isinstance(roster_reason_values, list) and
             set(roster_reason_values) == {
                 "exact_full_card_official_roster_match",
                 "official_roster_id_name_or_distance_mismatch",
                 "no_exact_full_card_source_roster",
             }, "full-card roster reason vocabulary differs from the audited states")
    _require(isinstance(denominator_source_statuses, list) and denominator_source_statuses and
             all(isinstance(item, str) and item for item in denominator_source_statuses),
             "source contract must enumerate declaration-denominator source statuses")
    _require(set(denominator_source_statuses) == set(confirmed_roster_statuses),
             "denominator source statuses must be exactly the confirmed full-roster status set")
    confirmed_mask = roster_confirmed
    _require(audit.loc[confirmed_mask, "full_card_roster_status"].astype(str).isin(
        set(confirmed_roster_statuses)).all(),
        "confirmed full declaration roster has an unapproved status")
    _require(audit.loc[~confirmed_mask, "full_card_roster_status"].astype(str).isin(
        set(roster_status_values) - set(confirmed_roster_statuses)).all(),
        "unconfirmed full declaration roster has an unapproved status")
    _require(audit.full_card_roster_reason.astype(str).isin(set(roster_reason_values)).all(),
             "full-card roster reason is not in the audited reason vocabulary")
    _require(audit.loc[confirmed_mask, "max_declared_horse_number_source_document_id"].notna().all(),
             "confirmed entry-number denominator lacks its source document ID")
    _require(audit.loc[confirmed_mask, "max_declared_horse_number_source_status"].astype(str).isin(
        set(denominator_source_statuses)).all(),
        "confirmed entry-number denominator has an unapproved source status")
    denominator_source_status = audit.max_declared_horse_number_source_status.astype(str)
    _require(denominator_source_status.loc[confirmed_mask].eq("full_card_roster_exact").all() and
             denominator_source_status.loc[~confirmed_mask].eq("unconfirmed").all(),
             "denominator source status does not match the confirmed/unconfirmed full-roster state")
    denominator_doc_id = audit.max_declared_horse_number_source_document_id
    denominator_doc_hash = audit.max_declared_horse_number_source_document_sha256
    denominator_doc_date = pd.to_datetime(audit.max_declared_horse_number_source_file_date, errors="coerce")
    _require(denominator_doc_id.loc[confirmed_mask].notna().all() and
             denominator_doc_id.loc[confirmed_mask].astype(str).map(bool).all(),
             "confirmed entry-number denominator lacks its source document ID")
    _require(denominator_doc_hash.loc[confirmed_mask].astype(str).str.fullmatch(
        r"[0-9a-f]{64}").all(), "confirmed entry-number denominator has invalid source document SHA256")
    _require(denominator_doc_date.loc[confirmed_mask].notna().all(),
             "confirmed entry-number denominator lacks its source document date")
    denominator_target_dates = pd.to_datetime(audit.race_date, errors="coerce")
    _require((denominator_doc_date.loc[confirmed_mask].reset_index(drop=True) <=
              (denominator_target_dates.loc[confirmed_mask] - pd.Timedelta(days=2)).reset_index(drop=True)).all(),
             "confirmed entry-number source document violates the fixed T−2 builder cutoff")
    unconfirmed_source_proof = (
        "max_declared_horse_number_source_document_id", "max_declared_horse_number_source_file_date",
        "max_declared_horse_number_source_document_sha256",
    )
    _require(not audit.loc[~confirmed_mask, list(unconfirmed_source_proof)].notna().any().any(),
             "an unconfirmed entry-number denominator retains source document proof")
    _require((audit.groupby("race_id", sort=False).max_declared_horse_number.nunique(dropna=False) == 1).all(),
             "max_declared_horse_number changes within a target race")
    _require((audit.groupby("race_id", sort=False).max_full_card_declared_horse_number.nunique(dropna=False) == 1).all(),
             "max_full_card_declared_horse_number changes within a target race")
    _require((audit.groupby("race_id", sort=False).full_card_roster_confirmed.nunique(dropna=False) == 1).all(),
             "full-card roster confirmation changes within a target race")
    _require((audit.groupby("race_id", sort=False).event_number.nunique() == 1).all(),
             "event_number changes within a target race")
    target_roster_max = audit.groupby("race_id", sort=False).horse_number.transform("max").to_numpy(dtype=np.float64)
    _require((max_declared_number[np.isfinite(max_declared_number)] ==
              target_roster_max[np.isfinite(max_declared_number)]).all(),
             "confirmed declaration denominator differs from the S40 target roster maximum")
    _require(np.array_equal(np.isfinite(full_card_max), confirmed_mask) and
             np.array_equal(full_card_max[confirmed_mask], target_roster_max[confirmed_mask]),
             "full-card maximum must equal the S40 roster maximum only when the full roster is confirmed")
    _require(np.array_equal(np.isfinite(full_card_max), confirmed_mask) and
             np.array_equal(full_card_max[confirmed_mask], target_roster_max[confirmed_mask]),
             "full-card maximum must equal the S40 roster maximum only when the full roster is confirmed")
    both_numbers_known = np.isfinite(declared_number) & np.isfinite(max_declared_number)
    _require((declared_number[both_numbers_known] <= max_declared_number[both_numbers_known]).all(),
             "declared horse number exceeds its target-race declared maximum")
    expected_fraction = np.full(len(audit), np.nan, dtype=np.float64)
    ratio_rows = both_numbers_known & (max_declared_number > 1)
    expected_fraction[ratio_rows] = ((declared_number[ratio_rows] - 1.0) /
                                     (max_declared_number[ratio_rows] - 1.0))
    actual_fraction = _numeric_or_missing(audit.horse_number_fraction, "horse_number_fraction")
    _require(np.array_equal(np.isnan(actual_fraction), ~ratio_rows) and
             ((actual_fraction[ratio_rows] >= 0.0) & (actual_fraction[ratio_rows] <= 1.0)).all() and
             np.allclose(actual_fraction[ratio_rows], expected_fraction[ratio_rows], atol=1e-12, rtol=0.0),
             "horse_number_fraction does not match the fixed formula")

    current_weight = _numeric_or_missing(audit.current_declared_burden_kg, "current declared burden")
    previous_weight = _numeric_or_missing(audit.latest_prior_burden_kg, "latest prior burden")
    delta = _numeric_or_missing(audit.burden_change_vs_last_valid_kg, "burden change")
    snapshot_complete_series = audit.prior_source_snapshot_complete
    _require(snapshot_complete_series.notna().all() and
             snapshot_complete_series.map(lambda value: isinstance(value, (bool, np.bool_))).all(),
             "prior actual-result snapshot completeness must be explicit boolean per target row")
    snapshot_complete = snapshot_complete_series.to_numpy(dtype=bool)
    fallback_series = audit.latest_prior_fallback_after_ambiguous_special
    _require(fallback_series.notna().all() and
             fallback_series.map(lambda value: isinstance(value, (bool, np.bool_))).all(),
             "prior ambiguous-special fallback must be explicit boolean per target row")
    fallback_used = fallback_series.to_numpy(dtype=bool)
    _require(((current_weight > 0.0) | np.isnan(current_weight)).all(), "current burden must be positive kg or missing")
    _require(((previous_weight > 0.0) | np.isnan(previous_weight)).all(), "prior burden must be positive kg or missing")
    expected_delta = current_weight - previous_weight
    both_known = np.isfinite(current_weight) & np.isfinite(previous_weight)
    eligible_delta = both_known & snapshot_complete
    _require(np.array_equal(np.isnan(delta), ~eligible_delta),
             "burden change must be missing without current/prior values or a complete prior snapshot")
    _require(np.allclose(delta[eligible_delta], expected_delta[eligible_delta], atol=1e-12, rtol=0.0),
             "burden change does not equal current minus latest prior kg")
    prior_dates = pd.to_datetime(audit.latest_prior_race_date, errors="coerce")
    target_dates = pd.to_datetime(audit.race_date, errors="coerce")
    prior_present = np.isfinite(previous_weight)
    prior_status = audit.latest_prior_status.astype(str)
    valid_prior_statuses = set(LATEST_PRIOR_VALID_STATUSES)
    missing_prior_statuses = set(LATEST_PRIOR_MISSING_STATUSES)
    _require(set(prior_status.unique()).issubset(valid_prior_statuses | missing_prior_statuses),
             "latest prior actual-result status is not in the frozen status contract")
    _require(np.array_equal(prior_present, prior_status.isin(valid_prior_statuses).to_numpy()),
             "latest prior burden value/status consistency failed")
    _require(not fallback_used[~prior_present].any(),
             "a row without a valid prior burden cannot carry the ambiguous-special fallback flag")
    truncated_statuses = {
        "latest_observed_through_snapshot_cutoff_not_complete_asof_T_minus_2",
        "source_snapshot_truncated_before_cutoff_no_observed_prior",
    }
    _require(np.array_equal(~snapshot_complete, prior_status.isin(truncated_statuses).to_numpy()),
             "prior status does not match actual-result snapshot completeness")
    fallback_status = prior_status.eq("fallback_after_ambiguous_special_92").to_numpy()
    fallback_or_snapshot_truncated = np.isin(
        prior_status.to_numpy(), ["fallback_after_ambiguous_special_92",
                                  "latest_observed_through_snapshot_cutoff_not_complete_asof_T_minus_2"])
    _require((~fallback_status | fallback_used).all() and
             (~fallback_used | fallback_or_snapshot_truncated).all(),
             "ambiguous-special fallback flag does not match its prior-row status")
    prior_cutoff = pd.to_datetime(audit.latest_prior_cutoff, errors="coerce")
    expected_cutoff = target_dates - pd.Timedelta(days=2)
    _require(prior_cutoff.notna().all() and
             prior_cutoff.reset_index(drop=True).eq(expected_cutoff.reset_index(drop=True)).all(),
             "latest prior cutoff field differs from the fixed T−2 date rule")
    valid_prior_start = audit.loc[prior_present, "latest_prior_start_class"].astype(str)
    _require(valid_prior_start.isin(set(LATEST_PRIOR_VALID_START_CLASSES)).all(),
             "latest prior actual row start class is not an eligible actual-start class")
    _require(((previous_weight[prior_present] >= 30.0) & (previous_weight[prior_present] <= 100.0)).all(),
             "latest prior actual burden is outside the fixed 30–100 kg eligibility range")
    _require(prior_dates.notna().to_numpy().sum() == int(prior_present.sum()),
             "latest prior burden/date coverage differs")
    missing_prior = ~prior_present
    prior_lineage_columns = (
        "latest_prior_race_date", "latest_prior_race_id", "latest_prior_horse_id", "latest_prior_source_row_id",
        "latest_prior_source_row_sha256", "latest_prior_source_artifact_id",
        "latest_prior_source_artifact_path", "latest_prior_source_artifact_sha256",
        "latest_prior_source_line_number", "latest_prior_start_class",
    )
    _require(not audit.loc[missing_prior, prior_lineage_columns].notna().any().any(),
             "a row without a valid prior burden retains stray actual-result lineage")
    cutoff = target_dates - pd.Timedelta(days=2)
    _require((prior_dates.loc[prior_present].reset_index(drop=True) <=
              cutoff.loc[prior_present].reset_index(drop=True)).all(),
             "latest prior burden violates inclusive T−2 date cutoff")
    _require(audit.loc[prior_present, "latest_prior_race_id"].notna().all(),
             "latest prior burden lacks a source race key")
    _require(audit.loc[prior_present, "latest_prior_horse_id"].astype(str).eq(
        audit.loc[prior_present, "horse_id"].astype(str)).all(),
        "latest prior burden is not keyed to the same official horse ID")
    _require(audit.loc[prior_present, "latest_prior_race_id"].astype(str).ne(
        audit.loc[prior_present, "race_id"].astype(str)).all(),
        "latest prior burden points to the target race itself")
    _require(audit.loc[prior_present, "latest_prior_source_row_id"].notna().all(),
             "latest prior actual burden lacks its actual-result source row key")
    _require(audit.latest_prior_source_row_id.loc[prior_present].astype(str).map(bool).all() and
             audit.latest_prior_source_artifact_id.loc[prior_present].astype(str).map(bool).all() and
             audit.latest_prior_source_artifact_path.loc[prior_present].astype(str).map(bool).all() and
             audit.latest_prior_start_class.loc[prior_present].astype(str).map(bool).all() and
             audit.latest_prior_status.loc[prior_present].astype(str).map(bool).all(),
             "latest prior actual burden lacks start/status/artifact lineage")
    for column in ("latest_prior_source_row_sha256", "latest_prior_source_artifact_sha256"):
        hashes = audit.loc[prior_present, column].astype(str)
        _require(hashes.str.fullmatch(r"[0-9a-f]{64}").all(),
                 f"latest prior actual burden has invalid {column}")
    prior_line = pd.to_numeric(audit.latest_prior_source_line_number.loc[prior_present], errors="coerce")
    _require(np.isfinite(prior_line.to_numpy(dtype=np.float64)).all() and
             (prior_line.to_numpy(dtype=np.float64) >= 1).all() and
             np.equal(prior_line.to_numpy(dtype=np.float64), np.rint(prior_line.to_numpy(dtype=np.float64))).all(),
             "latest prior actual burden has invalid source line number")
    _require(audit.source_type.astype(str).eq(expected_source_type).all(),
             "row source_type differs from the audit contract")
    _require(audit.publication_time_status.astype(str).eq(expected_publication_status).all(),
             "row publication_time_status differs from the audit contract")
    _require(audit.burden_status.notna().all() and audit.number_status.notna().all(),
             "audit must retain explicit burden and number statuses")
    if expected_source_type == "dacom01_h3_dated_declaration":
        current_present = np.isfinite(current_weight)
        _require(audit.current_source_status.notna().all(),
                 "audit must retain explicit current declaration match status")
        _require(audit.loc[current_present, "entry_id"].notna().all(),
                 "current declared burdens lack matched H3 entry keys")
        _require(audit.loc[current_present, "source_document_id"].notna().all(),
                 "H3 declaration rows lack source-document IDs")
        _require(audit.loc[current_present, "source_file_date"].notna().all(),
                 "H3 declaration rows lack dated-document dates")
        target_dates = pd.to_datetime(audit.race_date, errors="coerce")
        declaration_dates = pd.to_datetime(audit.source_file_date, errors="coerce")
        cutoff_dates = target_dates - pd.Timedelta(days=2)
        _require((declaration_dates.loc[current_present].reset_index(drop=True) <=
                  cutoff_dates.loc[current_present].reset_index(drop=True)).all(),
                 "current H3 declaration source date violates the fixed T−2 builder cutoff")
        for column in ("source_document_sha256", "source_line_sha256"):
            hashes = audit.loc[current_present, column].astype(str)
            _require(hashes.str.fullmatch(r"[0-9a-f]{64}").all(),
                     f"current H3 declaration has invalid {column}")
        _require(audit.loc[current_present, "source_raw_horse_name"].astype(str).map(bool).all(),
                 "current H3 declaration lacks its raw source horse name")
        current_status = audit.loc[current_present, "current_source_status"].astype(str)
        allowed_current_status = {"dacom01_exact_name_match", "dacom01_direct_single_star_marker_match"}
        _require(set(current_status.unique()).issubset(allowed_current_status),
                 "current H3 declaration has an unapproved source-match status")
        star = current_status.eq("dacom01_direct_single_star_marker_match")
        star_names = audit.loc[current_present].loc[star, "source_raw_horse_name"].astype(str)
        _require(star_names.str.startswith("★").all() and star_names.str.len().gt(1).all(),
                 "direct star-marker H3 matches do not preserve the exact raw marker/name")
        ordinary_names = audit.loc[current_present].loc[~star, "source_raw_horse_name"].astype(str)
        _require(~ordinary_names.str.startswith("★").any(),
                 "star-marker raw source name is mislabeled as an ordinary H3 match")
        _require(not availability_verified and availability_assumption,
                 "H3 source must preserve date-only publication assumption")

    model_features = audit.loc[:, ["api_record_id", "race_id"]].copy()
    feature_values = {
        "current_declared_burden_kg": current_weight,
        "burden_change_vs_last_valid_kg": delta,
        "horse_number_fraction": actual_fraction,
    }
    for column in FEATURE_COLUMNS:
        model_features[column] = feature_values[column].astype(np.float64, copy=False)
    _require(list(model_features.columns) == ["api_record_id", "race_id", *FEATURE_COLUMNS] and
             len(model_features) == len(target) and model_features.api_record_id.is_unique,
             "model input contains extra fields or changed target row count")
    receipt = {
        "rows": int(len(model_features)),
        "races": int(model_features.race_id.nunique()),
        "feature_columns": list(FEATURE_COLUMNS),
        "source_type": expected_source_type,
        "publication_time_status": expected_publication_status,
        "pre_race_availability_verified": availability_verified,
        "pre_race_availability_assumption": availability_assumption,
        "current_burden_nonmissing_rows": int(np.isfinite(current_weight).sum()),
        "prior_burden_nonmissing_rows": int(np.isfinite(previous_weight).sum()),
        "burden_change_nonmissing_rows": int(np.isfinite(delta).sum()),
        "prior_source_snapshot_incomplete_rows": int((~snapshot_complete).sum()),
        "target_key_one_to_one": True,
        "number_fraction_formula_verified": NUMBER_FRACTION_FORMULA,
        "number_denominator_rule_verified": NUMBER_DENOMINATOR_RULE,
        "full_card_roster_confirmed_rows": int(roster_confirmed.sum()),
        "matched_h3_source_event_rows": int(matched_source_event.sum()),
        "declared_number_missing_rows": int(np.isnan(declared_number).sum()),
        "declared_number_fraction_missing_rows": int(np.isnan(actual_fraction).sum()),
        "target_vs_declared_horse_number_disagreement_rows": int(
            (np.isfinite(declared_number) &
             (declared_number != audit.horse_number.to_numpy(dtype=np.float64))).sum()),
        "target_vs_full_card_declared_max_disagreement_races": _count_full_card_max_disagreements(audit),
        "previous_weight_cutoff_verified": PREVIOUS_WEIGHT_RULE,
    }
    return model_features, receipt


def _count_full_card_max_disagreements(audit: pd.DataFrame) -> int:
    full = audit.groupby("race_id", sort=False).max_full_card_declared_horse_number.first().to_numpy(dtype=np.float64)
    target = audit.groupby("race_id", sort=False).horse_number.max().to_numpy(dtype=np.float64)
    both = np.isfinite(full) & np.isfinite(target)
    return int(np.count_nonzero(both & (full != target)))
