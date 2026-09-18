"""Distance-matched, opponent-adjusted historical form; no current weather input."""

from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from datetime import timedelta

import numpy as np

FEATURES = [
    "distance_surprise_mean3",
    "distance_surprise_trend3v3",
    "distance_surprise_best5_shrunk",
    "distance_valid_count6",
    "distance_time_relative_mean3",
    "distance_closing_finish_gap3",
    "wet_distance_surprise_mean6",
    "dry_distance_surprise_mean6",
    "wet_distance_count6",
    "dry_distance_count6",
]
DEFINITIONS = {
    "distance_surprise_mean3": (
        "같은 거리 최근 정상3회 실제 상대 승점"
        "−사전 Elo 기대 승점 합/(유효수+3)"
    ),
    "distance_surprise_trend3v3": (
        "같은 거리 정상6회 이상일 때 최근3회와"
        " 그전3회 축소 surprise 평균 차이"
    ),
    "distance_surprise_best5_shrunk": (
        "같은 거리 최근 정상5회 최고 su"
        "rprise × 유효수/(유효수+3)"
    ),
    "distance_valid_count6": (
        "같은 거리 최근 유효 "
        "정상 이력 수, 최대6"
    ),
    "distance_time_relative_mean3": (
        "같은 거리 최근 정상3회 (결승시간−그 경주"
        " 중앙값)/거리×100 평균, ms/100m"
    ),
    "distance_closing_finish_gap3": (
        "같은 거리 최근 정상3회 (막판200m 상"
        "대속도−실제 상대 승점) 합/(유효수+3)"
    ),
    "wet_distance_surprise_mean6": (
        "같은 거리 최근 정상6회 중 함수율10"
        "%이상 surprise 합/(유효수+3)"
    ),
    "dry_distance_surprise_mean6": (
        "같은 거리 최근 정상6회 중 함수율1~"
        "9% surprise 합/(유효수+3)"
    ),
    "wet_distance_count6": (
        "위 습한 주로 su"
        "rprise 관측 수"
    ),
    "dry_distance_count6": (
        "위 건조/양호 주로 s"
        "urprise 관측 수"
    ),
}


def finite(value):
    return value is not None and np.isfinite(value)


def adjusted_history(history):
    """Pairwise observed score and pre-race Elo expectation use the same rivals."""
    groups = defaultdict(list)
    for row in history:
        groups[row["race_id"]].append(dict(row))
    result = []
    for rows in groups.values():
        normal = [
            r
            for r in rows
            if finite(r.get("finish_position"))
            and 1 <= r["finish_position"] <= r["field_size"]
            and finite(r.get("global_elo_pre"))
        ]
        for row in rows:
            row["surprise"] = None
            row["observed_pair_score"] = None
            if row in normal:
                rivals = [r for r in normal if r["entry_id"] != row["entry_id"]]
                if rivals:
                    actual = np.mean(
                        [
                            float(row["finish_position"] < r["finish_position"])
                            + 0.5 * float(row["finish_position"] == r["finish_position"])
                            for r in rivals
                        ]
                    )
                    expected = np.mean(
                        [
                            1
                            / (
                                1
                                + 10
                                ** np.clip(
                                    (r["global_elo_pre"] - row["global_elo_pre"]) / 400, -20, 20
                                )
                            )
                            for r in rivals
                        ]
                    )
                    row["observed_pair_score"] = float(actual)
                    row["surprise"] = float(actual - expected)
            result.append(row)
    return result


def shrunk(values):
    values = [v for v in values if finite(v)]
    return float(sum(values) / (len(values) + 3)) if values else float("nan")


def build_features(targets, history):
    bykey = defaultdict(list)
    for r in adjusted_history(history):
        if finite(r["surprise"]):
            bykey[(r["horse_id"], r["distance_m"])].append(r)
    for rows in bykey.values():
        rows.sort(key=lambda r: (r["event_date"], r["race_id"]))
    dates = {k: [r["event_date"] for r in rows] for k, rows in bykey.items()}
    output = []
    lineage = []
    for t in targets:
        key = (t["horse_id"], t["distance_m"])
        cutoff = t["event_date"] - timedelta(days=2)
        n = bisect_right(dates.get(key, []), cutoff)
        prior = bykey[key][max(0, n - 6) : n]
        last3 = prior[-3:]
        last5 = prior[-5:]
        wet = [
            r
            for r in prior
            if finite(r.get("track_moisture_percent")) and 10 <= r["track_moisture_percent"] <= 100
        ]
        dry = [
            r
            for r in prior
            if finite(r.get("track_moisture_percent")) and 1 <= r["track_moisture_percent"] < 10
        ]
        time = [
            r["time_minus_race_median_ms"] / r["distance_m"] * 100
            for r in last3
            if finite(r.get("time_minus_race_median_ms"))
        ]
        gaps = [
            r["closing_speed_quality"] - r["observed_pair_score"]
            for r in last3
            if finite(r.get("closing_speed_quality"))
        ]
        result = dict(
            entry_id=t["entry_id"],
            distance_surprise_mean3=shrunk([r["surprise"] for r in last3]),
            distance_surprise_trend3v3=(
                shrunk([r["surprise"] for r in last3]) - shrunk([r["surprise"] for r in prior[:3]])
            )
            if len(prior) == 6
            else float("nan"),
            distance_surprise_best5_shrunk=max((r["surprise"] for r in last5), default=float("nan"))
            * len(last5)
            / (len(last5) + 3),
            distance_valid_count6=float(len(prior)),
            distance_time_relative_mean3=float(np.mean(time)) if time else float("nan"),
            distance_closing_finish_gap3=shrunk(gaps),
            wet_distance_surprise_mean6=shrunk([r["surprise"] for r in wet]),
            dry_distance_surprise_mean6=shrunk([r["surprise"] for r in dry]),
            wet_distance_count6=float(len(wet)),
            dry_distance_count6=float(len(dry)),
        )
        output.append(result)
        lineage.append(
            dict(
                entry_id=t["entry_id"],
                event_date=t["event_date"],
                cutoff_date=cutoff,
                max_history_date=prior[-1]["event_date"] if prior else None,
                source_entry_ids=[r["entry_id"] for r in prior],
            )
        )
    return output, lineage
