"""Synthetic boundary checks for first-start trial aggregation; no DB/model access."""
from __future__ import annotations

import numpy as np
import pandas as pd

from feature_core import ADDED_FEATURES, add_features


def event_rows(date: str, number: int, target_time: float | None, target_eligible: bool,
               post_cutoff: bool = False) -> list[dict]:
    key = f"{date}|2|{number}"
    rows = [
        {
            "source_api_record_id": number * 100 + 1,
            "trial_event_key": key,
            "trial_event_order": number,
            "trial_date": date,
            "meet_code": 2,
            "trial_day_serial": number,
            "horse_id": "11",
            "breed_label_raw": "제주",
            "finish_time_seconds": target_time,
            "trial_ord_raw": "93" if not target_eligible else "1",
            "trial_judgment_raw": "합격",
            "time_eligible": target_eligible,
        },
        {
            "source_api_record_id": number * 100 + 2,
            "trial_event_key": key,
            "trial_event_order": number,
            "trial_date": date,
            "meet_code": 2,
            "trial_day_serial": number,
            "horse_id": "21",
            "breed_label_raw": "제주",
            "finish_time_seconds": 100.0,
            "trial_ord_raw": "1",
            "trial_judgment_raw": "합격",
            "time_eligible": True,
        },
        {
            "source_api_record_id": number * 100 + 3,
            "trial_event_key": key,
            "trial_event_order": number,
            "trial_date": date,
            "meet_code": 2,
            "trial_day_serial": number,
            "horse_id": "22",
            "breed_label_raw": "제주",
            "finish_time_seconds": 110.0,
            "trial_ord_raw": "2",
            "trial_judgment_raw": "합격",
            "time_eligible": True,
        },
    ]
    if post_cutoff:
        rows[0]["source_api_record_id"] += 10000
    return rows


def run() -> None:
    baseline = pd.DataFrame({
        "api_record_id": [100, 101, 102],
        "race_id": ["r1", "r2", "r3"],
        "race_date": ["2026-01-20", "2026-01-20", "2026-01-20"],
        "history_cutoff": ["2026-01-18", "2026-01-18", "2026-01-18"],
        "horse_id": ["11", "99", "98"],
        "observed_starts": [0, 0, 1],
        "existing_input": [1.25, np.nan, -4.0],
    })
    targets = baseline.loc[baseline.observed_starts.eq(0), [
        "api_record_id", "race_id", "race_date", "history_cutoff", "horse_id", "observed_starts"
    ]].copy()

    source = pd.DataFrame(
        event_rows("2026-01-01", 1, 90.0, True)
        + event_rows("2026-01-05", 2, 120.0, True)
        + event_rows("2026-01-10", 3, 130.0, True)
        # A positive raw time is held because of an invalid rank/judgment in
        # the audited eligibility rule. It remains a history slot/count.
        + event_rows("2026-01-18", 4, 150.0, False)
        + event_rows("2026-01-19", 5, 200.0, True, post_cutoff=True)
    )
    features, ledger = add_features(baseline, targets, source)

    first = features.loc[features.api_record_id.eq(100)].iloc[0]
    assert first.trial_event_count_pre == 4
    assert first.trial_days_since_latest_event_pre == 2
    assert first.trial_peer_relative_time_n3 == 2
    expected = np.mean([(120.0 - 105.0) / 105.0, (130.0 - 105.0) / 105.0])
    assert np.isclose(first.trial_peer_relative_time_mean3, expected, rtol=0, atol=1e-15)
    first_ledger = ledger.loc[ledger.target_api_record_id.eq(100)]
    assert first_ledger.source_trial_date.tolist() == ["2026-01-05", "2026-01-10", "2026-01-18"]
    assert first_ledger.source_time_eligible.tolist() == [True, True, False]
    assert first_ledger.loc[first_ledger.source_trial_date.eq("2026-01-18"), "source_time_seconds"].iloc[0] == 150.0
    assert first_ledger.loc[first_ledger.source_trial_date.eq("2026-01-18"), "relative_time"].isna().all()
    assert "2026-01-19" not in set(first_ledger.source_trial_date)

    no_history = features.loc[features.api_record_id.eq(101)].iloc[0]
    assert no_history.trial_peer_relative_time_n3 == 0
    assert no_history.trial_event_count_pre == 0
    assert pd.isna(no_history.trial_peer_relative_time_mean3)
    assert pd.isna(no_history.trial_days_since_latest_event_pre)

    experienced = features.loc[features.api_record_id.eq(102), ADDED_FEATURES]
    assert experienced.isna().all().all()
    pd.testing.assert_frame_equal(
        features[baseline.columns].reset_index(drop=True), baseline.reset_index(drop=True), check_exact=True
    )

    # A target with only one valid peer must not receive a relative-time value.
    insufficient = source.loc[
        ~(source.trial_event_key.eq("2026-01-10|2|3") & source.horse_id.eq("22"))
    ].copy()
    one_peer_features, one_peer_ledger = add_features(baseline, targets, insufficient)
    one_peer = one_peer_ledger.loc[
        one_peer_ledger.target_api_record_id.eq(100)
        & one_peer_ledger.source_trial_event_key.eq("2026-01-10|2|3")
    ].iloc[0]
    assert one_peer.peer_positive_time_n == 1
    assert pd.isna(one_peer.relative_time)
    assert one_peer_features.loc[one_peer_features.api_record_id.eq(100), "trial_peer_relative_time_n3"].iloc[0] == 1

    print("feature_core synthetic checks passed: cutoff, newest-three/no-backfill, held positive time, peer exclusion, peer minimum, cold no-history, experienced NULLs, baseline preservation")


if __name__ == "__main__":
    run()
