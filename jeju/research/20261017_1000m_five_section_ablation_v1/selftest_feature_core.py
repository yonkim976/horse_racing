"""Synthetic, outcome-free invariance checks for feature_core."""
from __future__ import annotations

import numpy as np
import pandas as pd

from feature_core import SEGMENTS, add_history_features, derive_section_seconds


def main() -> None:
    endpoints = pd.DataFrame({
        "s1f_time_seconds": [14.0],
        "c3_time_seconds": [39.0],
        "c4_time_seconds": [52.0],
        "finish_time_seconds": [75.0],
        "g1f_time_seconds": [12.0],
    })
    derived = derive_section_seconds(endpoints)
    seconds = derived.iloc[0].to_numpy(dtype=float)
    assert np.array_equal(seconds, np.array([14.0, 25.0, 13.0, 11.0, 12.0]))
    assert np.isclose(seconds.sum(), 75.0, rtol=0, atol=1e-12)

    base = pd.DataFrame({
        "api_record_id": [103, 101, 102],
        "race_id": [203, 201, 202],
        "race_date": ["2025-07-12", "2025-07-10", "2025-07-11"],
        "distance_m": [1200, 1000, 1000],
        "base_input_probe": [7.0, 5.0, 6.0],
    })
    roster = pd.DataFrame({
        "api_record_id": [101, 102],
        "race_id": [201, 202],
        "race_date": ["2025-07-10", "2025-07-11"],
        "horse_id": ["h1", "h2"],
        "distance_m": [1000, 1000],
        "history_cutoff": ["2025-07-08", "2025-07-09"],
        "last5_same_source_ids": [[1001, 1002], []],
    })
    slots = pd.DataFrame({
        "target_api_record_id": [101, 101],
        "slot_oldest_to_newest": [1, 2],
        "source_api_record_id": [1001, 1002],
        "source_race_id": [301, 302],
        "source_race_date": ["2024-09-01", "2024-08-01"],
        "target_cutoff": ["2025-07-08", "2025-07-08"],
        "target_horse_id": ["h1", "h1"],
        "source_horse_id": ["h1", "h1"],
        "target_distance_m": [1000, 1000],
        "source_distance_m": [1000, 1000],
        "source_started": [True, True],
        "valid_time": [True, False],
        "s1f_time_seconds": [14.0, 24.0],
        "c3_time_seconds": [39.0, 59.0],
        "c4_time_seconds": [52.0, 72.0],
        "finish_time_seconds": [75.0, 105.0],
        "g1f_time_seconds": [12.0, 22.0],
    })
    segment_values = [14.0, 25.0, 13.0, 11.0, 12.0]
    invalid_time_slot_values = [24.0, 35.0, 13.0, 11.0, 22.0]
    for spec, value, invalid_time_slot_value in zip(
        SEGMENTS, segment_values, invalid_time_slot_values, strict=True
    ):
        slots[spec["raw_seconds"]] = [value, invalid_time_slot_value]
        slots[spec["quality_eligible"]] = [True, True]
        slots[spec["feature_eligible"]] = [True, False]
        slots[spec["feature_seconds"]] = [value, np.nan]

    candidate, lineage = add_history_features(base, roster, slots)
    assert len(candidate) == len(base) and len(lineage) == 2
    assert candidate.api_record_id.tolist() == base.api_record_id.tolist()
    for spec, expected in zip(SEGMENTS, segment_values, strict=True):
        assert candidate.loc[1, spec["mean"]] == expected
        assert candidate.loc[1, spec["n"]] == 1.0
        assert pd.isna(candidate.loc[2, spec["mean"]])
        assert candidate.loc[2, spec["n"]] == 0.0
        assert pd.isna(candidate.loc[0, spec["mean"]])
        assert pd.isna(candidate.loc[0, spec["n"]])
        assert lineage.loc[0, f"{spec['key']}_feature_eligible"]
        assert not lineage.loc[1, f"{spec['key']}_feature_eligible"]
        assert lineage.loc[1, f"{spec['key']}_ineligible_reason"] == "baseline_valid_time_false"
    assert candidate.loc[:, "base_input_probe"].equals(base.base_input_probe)


if __name__ == "__main__":
    main()
    print("feature_core synthetic checks passed")
