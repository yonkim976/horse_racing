"""Deterministic aggregation for the frozen five-section source bundle.

This module consumes only saved F1 feature/lineage parquet and the separately
frozen quality-source parquet. It never opens the project database or fits a
model.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd


SEGMENTS = (
    {
        "key": "seg_0_200",
        "formula_seconds": "seg_0_200_seconds",
        "raw_seconds": "seg_0_200_raw_delta_seconds",
        "quality_eligible": "seg_0_200_quality_eligible",
        "feature_seconds": "seg_0_200_feature_seconds",
        "feature_eligible": "seg_0_200_feature_eligible",
        "mean": "hist_0_200m_seconds_mean5",
        "n": "hist_0_200m_n",
    },
    {
        "key": "seg_200_to_c3_approx400",
        "formula_seconds": "seg_200_to_c3_approx400_seconds",
        "raw_seconds": "seg_200_to_c3_approx400_raw_delta_seconds",
        "quality_eligible": "seg_200_to_c3_approx400_quality_eligible",
        "feature_seconds": "seg_200_to_c3_approx400_feature_seconds",
        "feature_eligible": "seg_200_to_c3_approx400_feature_eligible",
        "mean": "hist_200_approx400m_seconds_mean5",
        "n": "hist_200_approx400m_n",
    },
    {
        "key": "seg_c3_approx400_to_c4_approx600",
        "formula_seconds": "seg_c3_approx400_to_c4_approx600_seconds",
        "raw_seconds": "seg_c3_approx400_to_c4_approx600_raw_delta_seconds",
        "quality_eligible": "seg_c3_approx400_to_c4_approx600_quality_eligible",
        "feature_seconds": "seg_c3_approx400_to_c4_approx600_feature_seconds",
        "feature_eligible": "seg_c3_approx400_to_c4_approx600_feature_eligible",
        "mean": "hist_approx400_approx600m_seconds_mean5",
        "n": "hist_approx400_approx600m_n",
    },
    {
        "key": "seg_c4_approx600_to_800",
        "formula_seconds": "seg_c4_approx600_to_800_seconds",
        "raw_seconds": "seg_c4_approx600_to_800_raw_delta_seconds",
        "quality_eligible": "seg_c4_approx600_to_800_quality_eligible",
        "feature_seconds": "seg_c4_approx600_to_800_feature_seconds",
        "feature_eligible": "seg_c4_approx600_to_800_feature_eligible",
        "mean": "hist_approx600_800m_seconds_mean5",
        "n": "hist_approx600_800m_n",
    },
    {
        "key": "seg_800_to_1000",
        "formula_seconds": "seg_800_to_1000_seconds",
        "raw_seconds": "seg_800_to_1000_raw_delta_seconds",
        "quality_eligible": "seg_800_to_1000_quality_eligible",
        "feature_seconds": "seg_800_to_1000_feature_seconds",
        "feature_eligible": "seg_800_to_1000_feature_eligible",
        "mean": "hist_800_1000m_seconds_mean5",
        "n": "hist_800_1000m_n",
    },
)
ADDED_FEATURES = [column for spec in SEGMENTS for column in (spec["mean"], spec["n"])]
MAX_HISTORY_SLOTS = 5


def _as_bool(series: pd.Series, name: str) -> pd.Series:
    """Require explicit booleans/0/1; never treat missing values as true."""
    if series.isna().any():
        raise AssertionError(f"{name} contains NULL")
    values = set(series.unique().tolist())
    if not values.issubset({True, False, 0, 1, np.bool_(True), np.bool_(False)}):
        raise AssertionError(f"{name} is not an explicit boolean domain: {values}")
    return series.astype(bool)


def _normalize_ids(value: Any) -> list[int]:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return []
    if isinstance(value, np.ndarray):
        value = value.tolist()
    if not isinstance(value, (list, tuple)):
        raise AssertionError(f"saved last5 ID value has unexpected type: {type(value)!r}")
    return [int(item) for item in value]


def derive_section_seconds(frame: pd.DataFrame) -> pd.DataFrame:
    """Return the five fixed interval formulas from selected endpoint seconds."""
    required = {
        "s1f_time_seconds", "c3_time_seconds", "c4_time_seconds",
        "finish_time_seconds", "g1f_time_seconds",
    }
    missing = required - set(frame.columns)
    if missing:
        raise AssertionError(f"missing endpoint time columns: {sorted(missing)}")
    result = pd.DataFrame(index=frame.index)
    s1f, c3, c4, finish, g1f = (
        pd.to_numeric(frame[column], errors="coerce")
        for column in (
            "s1f_time_seconds", "c3_time_seconds", "c4_time_seconds",
            "finish_time_seconds", "g1f_time_seconds",
        )
    )
    result[SEGMENTS[0]["formula_seconds"]] = s1f
    result[SEGMENTS[1]["formula_seconds"]] = c3 - s1f
    result[SEGMENTS[2]["formula_seconds"]] = c4 - c3
    result[SEGMENTS[3]["formula_seconds"]] = finish - g1f - c4
    result[SEGMENTS[4]["formula_seconds"]] = g1f
    return result


def add_history_features(
    base_features: pd.DataFrame,
    target_roster: pd.DataFrame,
    target_slots: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Append 10 target-level mean/n fields and return auditable slot rows.

    Source `_quality_eligible` flags must include the frozen quality-selected
    endpoint/time-status gates and full-race point masks. Source
    `_feature_eligible` additionally requires the existing F1 baseline
    `valid_time`; actual slots remain in the returned lineage when ineligible.
    """
    if "api_record_id" not in base_features or "api_record_id" not in target_roster:
        raise AssertionError("base feature and target roster require api_record_id")
    if not base_features.api_record_id.is_unique or not target_roster.api_record_id.is_unique:
        raise AssertionError("base feature and target roster keys must be unique")
    if set(ADDED_FEATURES) & set(base_features.columns):
        raise AssertionError("refusing to overwrite a pre-existing feature column")

    roster_required = {
        "api_record_id", "race_id", "race_date", "horse_id", "distance_m",
        "history_cutoff", "last5_same_source_ids",
    }
    missing = roster_required - set(target_roster.columns)
    if missing:
        raise AssertionError(f"target roster missing fields: {sorted(missing)}")
    slot_required = {
        "target_api_record_id", "slot_oldest_to_newest", "source_api_record_id",
        "source_race_id", "source_race_date", "target_cutoff", "target_horse_id",
        "source_horse_id", "target_distance_m", "source_distance_m", "source_started",
        "valid_time",
    }
    for spec in SEGMENTS:
        slot_required.update((spec["raw_seconds"], spec["quality_eligible"],
                              spec["feature_seconds"], spec["feature_eligible"]))
    missing = slot_required - set(target_slots.columns)
    if missing:
        raise AssertionError(f"last5 section source missing fields: {sorted(missing)}")

    base_ids = set(base_features.api_record_id.astype("int64"))
    roster = target_roster.copy()
    roster["api_record_id"] = roster.api_record_id.astype("int64")
    roster["horse_id"] = roster.horse_id.astype("string")
    roster["race_date"] = roster.race_date.astype("string")
    roster["history_cutoff"] = roster.history_cutoff.astype("string")
    assert set(roster.api_record_id).issubset(base_ids)
    assert pd.to_numeric(roster.distance_m, errors="coerce").eq(1000).all()
    assert not roster.horse_id.eq("3005648").any()
    target_date = pd.to_datetime(roster.race_date, errors="raise").dt.normalize()
    cutoff_date = pd.to_datetime(roster.history_cutoff, errors="raise").dt.normalize()
    assert cutoff_date.equals(target_date - pd.Timedelta(days=2)), (
        "target history_cutoff must equal KST race_date minus two calendar days"
    )

    target_ids = set(roster.api_record_id)
    slots = target_slots.copy()
    slots["target_api_record_id"] = slots.target_api_record_id.astype("int64")
    slots["source_api_record_id"] = slots.source_api_record_id.astype("int64")
    slots["slot_oldest_to_newest"] = slots.slot_oldest_to_newest.astype("int64")
    assert slots.target_api_record_id.isin(target_ids).all()
    assert not slots.duplicated(["target_api_record_id", "slot_oldest_to_newest"]).any()
    assert not slots.duplicated(["target_api_record_id", "source_api_record_id"]).any()
    if len(slots):
        _as_bool(slots.source_started, "source_started")
        assert slots.source_started.astype(bool).all()
        valid_time = _as_bool(slots.valid_time, "valid_time")
        slots["valid_time"] = valid_time
        assert slots.target_horse_id.astype("string").equals(slots.source_horse_id.astype("string"))
        assert pd.to_numeric(slots.target_distance_m, errors="coerce").eq(1000).all()
        assert pd.to_numeric(slots.source_distance_m, errors="coerce").eq(1000).all()
        assert slots.source_race_date.astype("string").le(slots.target_cutoff.astype("string")).all()
        assert slots.target_cutoff.astype("string").equals(
            slots.target_api_record_id.map(roster.set_index("api_record_id").history_cutoff).astype("string")
        )
        assert slots.target_horse_id.astype("string").equals(
            slots.target_api_record_id.map(roster.set_index("api_record_id").horse_id).astype("string")
        )
        assert slots.groupby("target_api_record_id").slot_oldest_to_newest.apply(
            lambda values: values.sort_values().tolist() == list(range(1, len(values) + 1))
        ).all()

    roster_id_lists = {
        int(row.api_record_id): _normalize_ids(row.last5_same_source_ids)
        for row in roster[["api_record_id", "last5_same_source_ids"]].itertuples(index=False)
    }
    observed_id_lists = {
        int(target_id): group.sort_values("slot_oldest_to_newest", kind="stable")
        .source_api_record_id.astype("int64").tolist()
        for target_id, group in slots.groupby("target_api_record_id", sort=False)
    }
    for target_id, expected_ids in roster_id_lists.items():
        assert observed_id_lists.get(target_id, []) == expected_ids, (
            f"saved F1 last5 roster mismatch for target {target_id}"
        )

    slot_features = slots[[
        "target_api_record_id", "slot_oldest_to_newest", "source_api_record_id",
        "source_race_id", "source_race_date", "source_horse_id", "valid_time",
    ]].copy()
    formula_frame = derive_section_seconds(slots)
    for spec in SEGMENTS:
        raw_seconds = pd.to_numeric(slots[spec["raw_seconds"]], errors="coerce")
        formula_seconds = pd.to_numeric(formula_frame[spec["formula_seconds"]], errors="coerce")
        assert np.allclose(raw_seconds, formula_seconds, rtol=0, atol=1e-12, equal_nan=True), (
            f"source interval formula mismatch: {spec['key']}"
        )
        quality_eligible = _as_bool(slots[spec["quality_eligible"]], spec["quality_eligible"])
        eligible = _as_bool(slots[spec["feature_eligible"]], spec["feature_eligible"])
        assert eligible.equals(quality_eligible & slots.valid_time), (
            f"feature eligibility must equal quality eligibility and valid_time: {spec['key']}"
        )
        feature_seconds = pd.to_numeric(slots[spec["feature_seconds"]], errors="coerce")
        assert not (quality_eligible & (~raw_seconds.gt(0) | raw_seconds.isna())).any(), (
            f"source marks a nonpositive/missing interval quality-eligible: {spec['key']}"
        )
        assert feature_seconds.notna().equals(eligible), (
            f"feature seconds must be populated exactly at eligible slots: {spec['key']}"
        )
        assert np.allclose(feature_seconds, raw_seconds.where(eligible), rtol=0, atol=1e-12, equal_nan=True)
        slot_features[f"{spec['key']}_seconds"] = feature_seconds
        slot_features[f"{spec['key']}_source_quality_eligible"] = quality_eligible
        slot_features[f"{spec['key']}_feature_eligible"] = eligible
        slot_features[f"{spec['key']}_ineligible_reason"] = np.select(
            [~quality_eligible, quality_eligible & ~slots.valid_time],
            ["source_quality_or_interval_gate", "baseline_valid_time_false"],
            default="eligible",
        )

    additions = pd.DataFrame({"api_record_id": roster.api_record_id.to_numpy(dtype="int64")})
    slot_groups = {int(key): group for key, group in slot_features.groupby("target_api_record_id", sort=False)}
    for spec in SEGMENTS:
        means: list[float] = []
        counts: list[int] = []
        for target_id in additions.api_record_id:
            group = slot_groups.get(int(target_id))
            if group is None:
                values = np.empty(0, dtype=float)
            else:
                eligible = group[f"{spec['key']}_feature_eligible"].to_numpy(dtype=bool)
                values = group.loc[eligible, f"{spec['key']}_seconds"].to_numpy(dtype=float)
            assert len(values) <= MAX_HISTORY_SLOTS
            counts.append(int(len(values)))
            means.append(float(values.mean()) if len(values) else np.nan)
        additions[spec["mean"]] = np.asarray(means, dtype="float64")
        additions[spec["n"]] = np.asarray(counts, dtype="float64")

    result = base_features.merge(additions, on="api_record_id", how="left", validate="one_to_one", sort=False)
    assert len(result) == len(base_features)
    assert result.api_record_id.astype("int64").equals(base_features.api_record_id.astype("int64"))
    target_mask = pd.to_numeric(result.distance_m, errors="coerce").eq(1000)
    roster_mask = result.api_record_id.astype("int64").isin(target_ids)
    assert target_mask.equals(roster_mask), "1000m target roster differs from saved F1 feature cohort"

    for spec in SEGMENTS:
        mean_col, n_col = spec["mean"], spec["n"]
        assert pd.api.types.is_numeric_dtype(result[mean_col])
        assert pd.api.types.is_numeric_dtype(result[n_col])
        assert result.loc[~target_mask, [mean_col, n_col]].isna().all().all()
        assert result.loc[target_mask, n_col].notna().all()
        assert result.loc[target_mask, n_col].between(0, MAX_HISTORY_SLOTS).all()
        assert result.loc[target_mask & result[n_col].eq(0), mean_col].isna().all()
        assert result.loc[target_mask & result[n_col].gt(0), mean_col].notna().all()

    # Preserve exact base feature row order; history lineage is key sorted for audit.
    slot_features = slot_features.sort_values(
        ["target_api_record_id", "slot_oldest_to_newest"], kind="stable"
    ).reset_index(drop=True)
    pd.testing.assert_frame_equal(
        result[base_features.columns].reset_index(drop=True),
        base_features[base_features.columns].reset_index(drop=True),
        check_exact=True,
    )
    return result, slot_features

