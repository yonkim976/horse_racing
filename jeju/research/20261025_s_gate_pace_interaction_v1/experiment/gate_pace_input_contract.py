"""Read-only consumer checks for the audit-owned S40/G47 thin input table.

The source-audit role computes and writes the seven model columns. This module
does not reopen phase-source rows or produce a replacement feature table. It
checks the source lineage and independently recomputes the fixed algebra from
the S40 target roster and the audited per-horse history summary before
returning only the seven numeric model columns.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import timedelta
from typing import Any

import numpy as np
import pandas as pd


FEATURE_COLUMNS = (
    "pace_own_early_tendency",
    "pace_own_label_support_fraction_max10",
    "pace_inner_interaction",
    "pace_outer_interaction",
    "pace_adjacent_inner_interaction",
    "pace_adjacent_outer_interaction",
    "pace_opponent_observed_fraction",
)
TARGET_KEYS = ("api_record_id", "race_id", "race_date", "horse_id", "horse_number", "field_n")
AUDIT_KEYS = (*TARGET_KEYS, "race_distance_m")
HISTORY_COLUMNS = ("h10_s1f_0_mean", "h10_s1f_0_n", "h10_slots", "early_tendency_q",
                   "history_cutoff", "history_lower", "h10_ids", "h10_dates")
PEER_LINEAGE_COLUMNS = tuple(
    f"{prefix}_{suffix}"
    for prefix in ("inner", "outer", "adjacent_inner", "adjacent_outer")
    for suffix in ("rival_api_record_ids", "rival_horse_ids", "rival_horse_numbers",
                   "rival_h10_s1f_0_n", "rival_support", "rival_q", "rival_q_sum")
)
SPEC_ID = "s_gate_pace_v1_7f"
EXPECTED_SOURCE = "jeju/research/20261021_phase_pace_prediction_v1/outputs/features_and_targets.parquet"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _integer_values(values: pd.Series, name: str, *, minimum: int = 0,
                    maximum: int | None = None) -> np.ndarray:
    numeric = pd.to_numeric(values, errors="coerce").to_numpy(dtype=np.float64)
    ok = np.isfinite(numeric) & np.equal(numeric, np.rint(numeric)) & (numeric >= minimum)
    if maximum is not None:
        ok &= numeric <= maximum
    _require(bool(ok.all()), f"{name} must contain exact integers in [{minimum}, {maximum}]")
    return numeric.astype(np.int64)


def _date_strings(values: pd.Series, name: str) -> pd.Series:
    parsed = pd.to_datetime(values, errors="coerce")
    _require(bool(parsed.notna().all()), f"{name} contains invalid dates")
    return parsed.dt.strftime("%Y-%m-%d")


def _list_length(value: Any, name: str) -> int:
    if value is None or value is pd.NA or (isinstance(value, float) and np.isnan(value)):
        return 0
    _require(isinstance(value, (list, tuple, np.ndarray)), f"{name} must be a list-valued lineage field")
    return len(value)


def _list_values(value: Any, name: str) -> list[Any]:
    _require(isinstance(value, (list, tuple, np.ndarray)), f"{name} must be a list-valued lineage field")
    return list(value)


def _close(actual: np.ndarray, expected: np.ndarray, name: str) -> None:
    _require(actual.dtype.kind in "fiu", f"{name} must be numeric")
    _require(np.isfinite(actual).all(), f"{name} must be finite for every target row")
    _require(np.allclose(actual.astype(np.float64), expected.astype(np.float64),
                         rtol=0.0, atol=1e-12), f"{name} does not match the frozen formula")


def _check_source_contract(contract: Mapping[str, Any], artifact_path: str,
                           artifact_bytes: int, artifact_sha256: str,
                           expected_rows: int, expected_races: int) -> dict[str, Any]:
    _require(contract.get("spec_id") == SPEC_ID, "source contract spec_id differs from the frozen G47 spec")
    _require(contract.get("feature_columns") == list(FEATURE_COLUMNS),
             "source contract feature order/names differ from the exact seven G47 inputs")
    artifact = contract.get("input_artifact")
    _require(isinstance(artifact, Mapping), "source contract input_artifact is missing")
    _require(artifact.get("path") == artifact_path and int(artifact.get("bytes", -1)) == artifact_bytes and
             artifact.get("sha256") == artifact_sha256,
             "audit input artifact path/format/bytes/SHA differs from the pinned artifact")
    _require(int(artifact.get("rows", -1)) == expected_rows,
             "audit input row inventory differs from S40")
    _require(artifact_bytes <= 8_000_000, "audit-owned thin feature artifact exceeds its 8 MB budget")
    references = contract.get("source_references")
    numeric_rules = contract.get("numeric_rules")
    support = contract.get("support")
    limitations = contract.get("limitations")
    _require(isinstance(references, (Mapping, list)) and bool(references),
             "source contract must retain source references")
    _require(isinstance(numeric_rules, Mapping) and bool(numeric_rules),
             "source contract must retain numeric rules")
    _require(isinstance(support, Mapping) and bool(support), "source contract support summary is missing")
    _require(isinstance(limitations, (Mapping, list)) and bool(limitations),
             "source contract limitations are missing")
    # Pin the six numerical rules by value without coupling the consumer to
    # wording or presentation-specific metadata keys.
    numeric_leaves: list[int | float] = []
    def collect(value: Any) -> None:
        if isinstance(value, Mapping):
            for child in value.values():
                collect(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                collect(child)
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            numeric_leaves.append(value)
    collect(numeric_rules)
    expected_rules = {"cutoff_lag_days": 2, "lookback_days": 730, "max_history_slots": 10,
                      "prior_positive": 1, "prior_strength": 3, "adjacent_number_gap": 1}
    for key, value in expected_rules.items():
        _require(numeric_rules.get(key) == value, f"numeric rule {key} differs from the frozen G47 contract")
    reference_paths = ([row.get("path") for row in references if isinstance(row, Mapping)]
                       if isinstance(references, list) else list(references.keys()))
    _require(EXPECTED_SOURCE in reference_paths, "source contract does not pin the phase-pace source path")
    return {"spec_id": SPEC_ID, "input_artifact": dict(artifact), "numeric_rules": dict(numeric_rules),
            "source_references": references, "support": support, "limitations": limitations}


def validate_audited_inputs(
    target_rows: pd.DataFrame,
    audit_features: pd.DataFrame,
    source_contract: Mapping[str, Any],
    *, artifact_path: str,
    artifact_bytes: int,
    artifact_sha256: str,
    expected_rows: int = 52_155,
    expected_races: int = 5_206,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Validate exact S40 row/key coverage and recompute G47 numeric invariants.

    ``target_rows`` is the frozen S40 frame. The audit artifact remains the
    only source of candidate features. Returned model matrix contains only
    the seven contract columns plus join keys.
    """
    contract_receipt = _check_source_contract(source_contract, artifact_path,
                                              artifact_bytes, artifact_sha256,
                                              expected_rows, expected_races)
    required = set(AUDIT_KEYS) | set(FEATURE_COLUMNS) | set(HISTORY_COLUMNS) | set(PEER_LINEAGE_COLUMNS)
    _require(required.issubset(audit_features.columns), "audit feature/lineage schema is incomplete")
    _require(set(TARGET_KEYS).issubset(target_rows.columns) and
             "distance_m" in target_rows.columns,
             "sealed S40 target key/distance schema is incomplete")
    prohibited = [column for column in audit_features.columns
                  if column.startswith(("y_", "obs_")) or column in {"finish_position", "finish_time_ms"}]
    _require(not prohibited, f"audit table contains target/outcome fields: {prohibited[:4]}")

    target = target_rows.loc[:, [*TARGET_KEYS, "distance_m"]].copy()
    audit = audit_features.loc[:, [*AUDIT_KEYS, *FEATURE_COLUMNS, *HISTORY_COLUMNS,
                                   *PEER_LINEAGE_COLUMNS]].copy()
    _require(len(target) == expected_rows and target.api_record_id.notna().all() and
             target.api_record_id.is_unique, "S40 target key inventory is incomplete or duplicated")
    _require(len(audit) == len(target) and audit.api_record_id.notna().all() and
             audit.api_record_id.is_unique, "audit API keys must be complete, unique and target-sized")
    target["race_date"] = _date_strings(target.race_date, "target race_date")
    audit["race_date"] = _date_strings(audit.race_date, "audit race_date")
    audit["history_cutoff"] = _date_strings(audit.history_cutoff, "history_cutoff")
    audit["history_lower"] = _date_strings(audit.history_lower, "history_lower")
    for frame in (target, audit):
        frame["api_record_id"] = _integer_values(frame.api_record_id, "api_record_id", minimum=1)
        frame["horse_number"] = _integer_values(frame.horse_number, "horse_number", minimum=1)
        frame["field_n"] = _integer_values(frame.field_n, "field_n", minimum=1)
        _require(frame.race_id.map(lambda x: isinstance(x, str) and bool(x)).all() and
                 frame.horse_id.map(lambda x: isinstance(x, str) and bool(x)).all(),
                 "target race_id/official horse_id must be non-empty strings")

    joined = target.merge(audit.loc[:, list(AUDIT_KEYS)], on="api_record_id", how="outer",
                          suffixes=("_target", "_audit"), validate="one_to_one", indicator=True)
    _require(len(joined) == len(target) == len(audit) and joined._merge.eq("both").all(),
             "audit API record IDs do not exactly cover the S40 target roster")
    for key in ("race_id", "race_date", "horse_id", "horse_number", "field_n"):
        _require(joined[f"{key}_target"].eq(joined[f"{key}_audit"]).all(),
                 f"audited {key} differs from the S40 target key")
    target_distance = pd.to_numeric(joined.distance_m, errors="coerce").to_numpy(dtype=np.float64)
    audit_distance = pd.to_numeric(joined.race_distance_m, errors="coerce").to_numpy(dtype=np.float64)
    _require(np.isfinite(target_distance).all() and np.array_equal(target_distance, audit_distance),
             "audit race distance differs from S40")
    _require(not audit.duplicated(["race_id", "horse_number"]).any(),
             "target race contains duplicate declared/result horse numbers")
    roster = audit.groupby("race_id", sort=False)
    roster_sizes = roster.api_record_id.size()
    _require(roster_sizes.eq(roster.field_n.first()).all(), "audit roster size differs from S40 field_n")
    _require(roster.field_n.nunique().eq(1).all() and roster.race_date.nunique().eq(1).all() and
             roster.race_distance_m.nunique().eq(1).all(), "race-level target keys are not invariant")
    _require(audit.race_id.nunique() == expected_races, "audit race count differs from the fixed target inventory")

    slot_n = _integer_values(audit.h10_slots, "h10_slots", minimum=0, maximum=10)
    label_n = _integer_values(audit.h10_s1f_0_n, "h10_s1f_0_n", minimum=0, maximum=10)
    _require((label_n <= slot_n).all(), "valid S1F label support exceeds observed history slots")
    mean = pd.to_numeric(audit.h10_s1f_0_mean, errors="coerce").to_numpy(dtype=np.float64)
    _require(np.isfinite(mean[label_n > 0]).all() and
             ((mean[label_n > 0] >= 0.0) & (mean[label_n > 0] <= 1.0)).all() and
             np.isnan(mean[label_n == 0]).all(),
             "history first-pack mean must be NULL at n=0 and a valid fraction at n>0")
    q = (np.where(label_n > 0, mean, 0.0) * label_n + 1.0) / (label_n + 3.0)
    saved_q = pd.to_numeric(audit.early_tendency_q, errors="coerce").to_numpy(dtype=np.float64)
    _require(np.isfinite(saved_q).all() and np.allclose(saved_q, q, rtol=0.0, atol=1e-12),
             "audited q does not match the fixed shrinkage formula")
    expected_cutoff = (pd.to_datetime(audit.race_date) - pd.to_timedelta(2, unit="D")).dt.strftime("%Y-%m-%d")
    expected_lower = (pd.to_datetime(audit.race_date) - pd.to_timedelta(730, unit="D")).dt.strftime("%Y-%m-%d")
    _require(audit.history_cutoff.eq(expected_cutoff).all() and audit.history_lower.eq(expected_lower).all(),
             "history window is not the exact inclusive T−730 through T−2 interval")
    for row_position, value in enumerate(audit.h10_ids.tolist()):
        _require(_list_length(value, "h10_ids") == int(slot_n[row_position]),
                 "h10_ids do not match the fixed maximum-10 actual-start slot count")
    for row_position, value in enumerate(audit.h10_dates.tolist()):
        _require(_list_length(value, "h10_dates") == int(slot_n[row_position]),
                 "h10_dates do not align one-to-one with the selected actual-start slots")
        dates = pd.to_datetime(list(value), errors="coerce")
        _require(bool(pd.notna(dates).all()), "h10_dates contains an invalid history date")
        lower = pd.Timestamp(audit.history_lower.iloc[row_position])
        cutoff = pd.Timestamp(audit.history_cutoff.iloc[row_position])
        _require(bool(((dates >= lower) & (dates <= cutoff)).all()),
                 "a selected h10 slot falls outside the inclusive T−730 through T−2 window")

    expected = np.empty((len(audit), len(FEATURE_COLUMNS)), dtype=np.float64)
    expected[:, 0] = q
    expected[:, 1] = label_n / 10.0
    expected[:, 2:] = 0.0
    positions = {api_id: index for index, api_id in enumerate(audit.api_record_id.tolist())}
    for _, group in audit.groupby("race_id", sort=False):
        indices = np.asarray([positions[value] for value in group.api_record_id.tolist()], dtype=np.int64)
        numbers = group.horse_number.to_numpy(dtype=np.int64)
        peer_q = q[indices]
        peer_observed = label_n[indices] > 0
        denominator = len(indices) - 1
        for local, global_i in enumerate(indices):
            inner = numbers < numbers[local]
            outer = numbers > numbers[local]
            adjacent_inner = numbers == numbers[local] - 1
            adjacent_outer = numbers == numbers[local] + 1
            masks = {"inner": inner, "outer": outer,
                     "adjacent_inner": adjacent_inner, "adjacent_outer": adjacent_outer}
            for prefix, mask in masks.items():
                row = audit.iloc[global_i]
                expected_numbers = numbers[mask]
                ordered_local = np.flatnonzero(mask)
                ordered_local = ordered_local[np.argsort(numbers[ordered_local], kind="stable")]
                expected_ids = group.api_record_id.to_numpy(dtype=np.int64)[ordered_local].tolist()
                expected_horse_ids = group.horse_id.astype(str).to_numpy()[ordered_local].tolist()
                expected_numbers = numbers[ordered_local].tolist()
                expected_n = label_n[indices][ordered_local].tolist()
                expected_support = (label_n[indices][ordered_local] > 0).tolist()
                expected_q = peer_q[ordered_local].tolist()
                for column, values in (
                    (f"{prefix}_rival_api_record_ids", expected_ids),
                    (f"{prefix}_rival_horse_ids", expected_horse_ids),
                    (f"{prefix}_rival_horse_numbers", expected_numbers),
                    (f"{prefix}_rival_h10_s1f_0_n", expected_n),
                    (f"{prefix}_rival_support", expected_support),
                    (f"{prefix}_rival_q", expected_q),
                ):
                    _require(_list_values(row[column], column) == values,
                             f"{column} is inconsistent with the exact same-race roster (self-exclusion/order)")
                lineage_sum = float(row[f"{prefix}_rival_q_sum"])
                _require(math_isclose(lineage_sum, float(peer_q[mask].sum())),
                         f"{prefix} rival-q sum differs from its lineage")
            expected[global_i, 2] = peer_q[inner].sum() * peer_q[local]
            expected[global_i, 3] = peer_q[outer].sum() * peer_q[local]
            expected[global_i, 4] = peer_q[adjacent_inner].sum() * peer_q[local]
            expected[global_i, 5] = peer_q[adjacent_outer].sum() * peer_q[local]
            expected[global_i, 6] = (float((peer_observed.sum() - int(peer_observed[local])) / denominator)
                                      if denominator > 0 else 0.0)
    model_values = np.empty_like(expected)
    for column_index, column in enumerate(FEATURE_COLUMNS):
        values = pd.to_numeric(audit[column], errors="coerce").to_numpy(dtype=np.float64)
        _close(values, expected[:, column_index], column)
        model_values[:, column_index] = values

    model_only = audit.loc[:, ["api_record_id", "race_id"]].copy()
    for index, column in enumerate(FEATURE_COLUMNS):
        model_only[column] = model_values[:, index].astype(np.float64)
    receipt = {
        "status": "PASS_AUDITED_G47_INPUTS",
        "spec_id": SPEC_ID,
        "rows": len(audit), "races": int(audit.race_id.nunique()),
        "feature_columns": list(FEATURE_COLUMNS),
        "history_label_support_rows": int((label_n > 0).sum()),
        "history_label_missing_rows": int((label_n == 0).sum()),
        "max10_slot_zero_rows": int((slot_n == 0).sum()),
        "minimum_history_n": int(label_n.min()), "maximum_history_n": int(label_n.max()),
        "history_window_verified": True,
        "same_target_roster_interactions_verified": True,
        "current_race_target_or_outcome_columns_read": False,
        "feature_formulas_verified_independently": True,
        "contract": contract_receipt,
    }
    return model_only, receipt


def math_isclose(left: float, right: float) -> bool:
    return bool(np.isfinite(left) and np.isfinite(right) and abs(left - right) <= 1e-12)
