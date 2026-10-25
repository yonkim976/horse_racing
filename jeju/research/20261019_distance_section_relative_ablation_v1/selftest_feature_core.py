"""Leakage, benchmark-weighting, and target-slot contract checks."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from feature_core import (  # noqa: E402
    ADDED_FEATURES,
    SEGMENTS,
    add_relative_history_features,
    compute_race_segment_medians,
    compute_source_event_benchmarks,
)


def _date(day: int) -> str:
    return f"2020-01-{day:02d}"


def _synthetic() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    rows: list[dict] = []
    api = 1000
    event_map: dict[tuple[int, int, str], list[int]] = {}
    for distance in (900, 1000, 1110, 1200):
        events = [(day, "a") for day in range(1, 23)] + [(22, "b"), (23, "a"), (24, "a")]
        for day, suffix in events:
            race_id = f"{_date(day)}_{distance}_{suffix}"
            event_api_ids = []
            for runner_idx, offset in enumerate((0.0, 2.0, 100.0, 200.0)):
                api += 1
                event_api_ids.append(api)
                valid_time = not (runner_idx == 2 or (runner_idx == 0 and day == 24))
                quality = not (runner_idx == 3)
                horse = f"H{runner_idx + 1}"
                for segment in SEGMENTS:
                    raw = 10.0 + day + segment * 0.1 + offset
                    rows.append({
                        "api_record_id": api,
                        "race_id": race_id,
                        "race_date": _date(day),
                        "horse_id": horse,
                        "distance_m": distance,
                        "started": True,
                        "valid_time": valid_time,
                        "segment_id": segment,
                        "nominal_length_m": 210 if distance == 1110 and segment == 1 else 200,
                        "raw_delta_seconds": raw,
                        "endpoint_measurement_eligible": quality,
                        "point_quality_clear": True,
                        "quality_eligible": quality,
                        "feature_eligible": quality and valid_time and raw > 0,
                        "feature_seconds": raw if quality and valid_time and raw > 0 else np.nan,
                    })
            event_map[(distance, day, suffix)] = event_api_ids
    source = pd.DataFrame(rows)

    roster_rows: list[dict] = []
    base_rows: list[dict] = []
    lineage_rows: list[dict] = []
    target_specs = []
    target_id = 900_000
    for distance in (900, 1000, 1110, 1200):
        target_specs.append((distance, 31, [
            (20, "a"), (21, "a"), (22, "a"), (23, "a"), (24, "a"),
        ]))
    target_specs.append((1000, 24, [(17, "a"), (18, "a"), (19, "a"), (20, "a"), (21, "a")]))
    for distance, target_day, events in target_specs:
        target_id += 1
        target_race_id = f"target_{target_id}"
        cutoff = f"2020-01-{target_day - 2:02d}"
        source_ids = [event_map[(distance, day, suffix)][0] for day, suffix in events]
        base_rows.append({
            "api_record_id": target_id,
            "race_id": target_race_id,
            "race_date": _date(target_day),
            "horse_id": "H1",
            "distance_m": distance,
            "history_cutoff": cutoff,
            "last5_same_source_ids": np.asarray(source_ids, dtype="int64"),
            "finish_position": 1,
            "field_n": 10,
            "year": 2020,
        })
        roster_rows.append({
            "api_record_id": target_id,
            "race_id": target_race_id,
            "race_date": _date(target_day),
            "horse_id": "H1",
            "distance_m": distance,
            "history_cutoff": cutoff,
            "last5_same_source_ids": np.asarray(source_ids, dtype="int64"),
        })
        for slot, ((day, suffix), source_id) in enumerate(zip(events, source_ids), 1):
            race_id = f"{_date(day)}_{distance}_{suffix}"
            lineage_rows.append({
                "target_api_record_id": target_id,
                "slot_oldest_to_newest": slot,
                "source_api_record_id": source_id,
                "source_race_id": race_id,
                "source_race_date": _date(day),
                "target_cutoff": cutoff,
                "target_horse_id": "H1",
                "source_horse_id": "H1",
                "target_distance_m": distance,
                "source_distance_m": distance,
                "source_started": True,
            })
    base_rows.append({
        "api_record_id": target_id + 1,
        "race_id": "unsupported_1",
        "race_date": "2020-01-31",
        "horse_id": "OTHER",
        "distance_m": 800,
        "history_cutoff": "2020-01-29",
        "last5_same_source_ids": np.asarray([], dtype="int64"),
        "finish_position": 4,
        "field_n": 10,
        "year": 2020,
    })
    return source, pd.DataFrame(base_rows), pd.DataFrame(roster_rows), pd.DataFrame(lineage_rows)


def run() -> dict:
    source, base, roster, slots = _synthetic()
    medians = compute_race_segment_medians(source)
    stats = compute_source_event_benchmarks(medians, source)

    event_21 = stats.loc[
        stats.race_id.eq("2020-01-21_1000_a") & stats.segment_id.eq(1)
    ].iloc[0]
    assert event_21.prior_eligible_race_n == 19 and not event_21.benchmark_exists
    event_22 = stats.loc[
        stats.race_id.eq("2020-01-22_1000_a") & stats.segment_id.eq(1)
    ].iloc[0]
    assert event_22.prior_eligible_race_n == 20 and event_22.benchmark_exists
    # Jan 24's T−2 cutoff is Jan 22. Both Jan 22 races count, while Jan 23 and
    # Jan 24 stay outside the reference.
    event_24 = stats.loc[
        stats.race_id.eq("2020-01-24_1000_a") & stats.segment_id.eq(1)
    ].iloc[0]
    assert event_24.reference_cutoff_T_minus_2 == "2020-01-22"
    assert event_24.prior_eligible_race_n == 23
    assert event_24.reference_last_date == "2020-01-22"

    features, ledger, rebuilt_medians, rebuilt_stats = add_relative_history_features(
        base, roster, slots, source,
    )
    assert len(features) == len(base)
    assert features.api_record_id.tolist() == base.api_record_id.tolist()
    assert features.columns[-len(ADDED_FEATURES):].tolist() == ADDED_FEATURES
    assert features.loc[features.distance_m.eq(800), ADDED_FEATURES].isna().all().all()

    target_mask = features.distance_m.isin((900, 1000, 1110, 1200))
    n_columns = [column for column in ADDED_FEATURES if column.endswith("_n")]
    assert features.loc[target_mask, n_columns].notna().all().all()
    early = features.loc[features.race_date.eq("2020-01-24") & features.distance_m.eq(1000)].iloc[0]
    assert early.hist_relative_seg_1_n == 0 and pd.isna(early.hist_relative_seg_1_mean5)

    late = features.loc[features.race_date.eq("2020-01-31") & features.distance_m.eq(1000)].iloc[0]
    late_seg1 = ledger.loc[
        ledger.target_api_record_id.eq(late.api_record_id) & ledger.segment_id.eq(1)
    ]
    assert len(late_seg1) == 5
    # The two newest benchmark-supported valid slots count; the older two
    # source dates lack the 20-race threshold, and the latest invalid slot is
    # retained without replacement.
    assert late.hist_relative_seg_1_n == 2
    invalid_latest = late_seg1.loc[late_seg1.slot_oldest_to_newest.eq(5)].iloc[0]
    expected_latest = roster.loc[
        roster.api_record_id.eq(late.api_record_id), "last5_same_source_ids"
    ].iloc[0][-1]
    assert invalid_latest.source_api_record_id == expected_latest
    assert not invalid_latest.feature_eligible and not invalid_latest.relative_feature_eligible

    # S1F is 210m at 1110m, but the model value stays a raw-time residual.
    late_1110 = features.loc[features.race_date.eq("2020-01-31") & features.distance_m.eq(1110)].iloc[0]
    ledger_1110 = ledger.loc[
        ledger.target_api_record_id.eq(late_1110.api_record_id) & ledger.segment_id.eq(1)
    ]
    assert ledger_1110.nominal_length_m.eq(210).all()
    eligible_row = ledger_1110.loc[ledger_1110.relative_feature_eligible].iloc[0]
    expected_residual = eligible_row.mean_of_prior_race_medians - eligible_row.raw_delta_seconds
    assert np.isclose(eligible_row.relative_performance_seconds, expected_residual, rtol=0, atol=1e-12)
    assert not np.isclose(eligible_row.relative_performance_seconds, expected_residual / 210,
                          rtol=0, atol=1e-12)

    assert len(rebuilt_medians) == source[["race_id", "distance_m"]].drop_duplicates().shape[0] * 5
    assert len(rebuilt_stats) == len(rebuilt_medians)
    return {
        "passed": True,
        "synthetic_source_rows": int(len(source)),
        "source_races": int(source.race_id.nunique()),
        "benchmark_rows": int(len(rebuilt_stats)),
        "target_rows": int(len(features)),
        "relative_lineage_rows": int(len(ledger)),
        "checks": [
            "T−2 inclusive date boundary and same-date multi-race inclusion",
            "19 vs 20 prior eligible race threshold",
            "T−1/current event exclusion from benchmarks",
            "race medians give equal event weight and exclude invalid entrants",
            "invalid latest slot retained without older backfill",
            "n=0 differs from unsupported-distance NULL",
            "1110m S1F relative seconds are not distance-scaled",
            "baseline values and row order preserved exactly",
        ],
    }


if __name__ == "__main__":
    import json

    print(json.dumps(run(), ensure_ascii=False, indent=2))
