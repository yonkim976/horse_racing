"""Strictly historical 800m trial features, separate from race performances."""

from bisect import bisect_right
from collections import defaultdict
from datetime import timedelta

import numpy as np

RECENCY_FEATURES = [
    "trial800_valid_count365",
    "trial800_days_since_last_valid",
    "trial800_days_since_last_attempt",
]
DETAIL_FEATURES = [
    "trial800_s1f_ms_mean3_365",
    "trial800_g1f_ms_mean3_365",
    "trial800_g3f_ms_mean3_365",
    "trial800_late_minus_early_ms_mean3_365",
    "trial800_finish_change_last2_365",
    "trial800_g1f_change_last2_365",
    "trial800_complete_section_count3_365",
]
FEATURES = RECENCY_FEATURES + DETAIL_FEATURES
DEFINITIONS = {
    RECENCY_FEATURES[0]: "T−365부터 T−2까지 정상·usable·양수 총기록인 800m 심사 수",
    RECENCY_FEATURES[1]: "T−2 이전 마지막 유효 800m 심사 이후 일수; 365일 제한 없음",
    RECENCY_FEATURES[2]: "T−2 이전 마지막 800m 심사 원장 행 이후 일수; 비양수 시도도 포함",
    DETAIL_FEATURES[0]: "최근365일 중 최근 유효 심사3회 S1F 200m 시간 평균(ms)",
    DETAIL_FEATURES[1]: "위3회 G1F 최종200m 시간 평균(ms)",
    DETAIL_FEATURES[2]: "위3회 G3F 최종600m 시간 평균(ms)",
    DETAIL_FEATURES[3]: "위3회 (G1F−S1F) 평균(ms); 음수는 막판200m가 더 빠름",
    DETAIL_FEATURES[4]: "최근365일 유효 심사 마지막2회 총시간의 마지막−이전(ms)",
    DETAIL_FEATURES[5]: "위 마지막2회 G1F의 마지막−이전(ms); 둘 다 관측 필요",
    DETAIL_FEATURES[6]: "위3회에서 S1F/G1F/G3F가 모두 유효한 심사 수(0~3)",
}


def finite(v):
    return v is not None and np.isfinite(v)


def valid_trial(row):
    return (
        row.get("distance_m") == 800
        and row.get("record_status") == "normal_completed"
        and row.get("segment_quality") == "usable"
        and finite(row.get("finish_time_ms"))
        and row["finish_time_ms"] > 0
    )


def section_value(row, code):
    section = row.get("sections", {}).get(code)
    if not valid_trial(row) or section is None:
        return None
    point = {"S1F": 200, "G1F": 600, "G3F": 200}[code]
    basis = "cumulative" if code == "S1F" else "closing"
    value = section.get("source_value_ms")
    if (
        section.get("time_basis") != basis
        or section.get("distance_from_start_m") != point
        or section.get("distance_is_approximate") != 0
        or not finite(value)
        or not 0 < value < row["finish_time_ms"]
    ):
        return None
    elapsed = value if basis == "cumulative" else row["finish_time_ms"] - value
    if section.get("elapsed_from_start_ms") != elapsed:
        return None
    return float(value)


def mean(values):
    a = [v for v in values if finite(v)]
    return float(np.mean(a)) if a else float("nan")


def build_features(targets, trials):
    byhorse = defaultdict(list)
    for row in trials:
        if row["distance_m"] == 800:
            byhorse[str(row["horse_id"])].append(row)
    for rows in byhorse.values():
        rows.sort(key=lambda r: (r["event_date"], r["entry_id"]))
    dates = {k: [r["event_date"] for r in v] for k, v in byhorse.items()}
    output = []
    lineage = []
    for t in targets:
        cutoff = t["event_date"] - timedelta(days=2)
        start = t["event_date"] - timedelta(days=365)
        horse = str(t["horse_id"])
        rows = byhorse.get(horse, [])
        prior = rows[: bisect_right(dates.get(horse, []), cutoff)]
        valid = [r for r in prior if valid_trial(r)]
        recent = [r for r in valid if r["event_date"] >= start]
        last3 = recent[-3:]
        s = [section_value(r, "S1F") for r in last3]
        g1 = [section_value(r, "G1F") for r in last3]
        g3 = [section_value(r, "G3F") for r in last3]
        finish_change = (
            recent[-1]["finish_time_ms"] - recent[-2]["finish_time_ms"]
            if len(recent) >= 2
            else float("nan")
        )
        late_change = (
            g1[-1] - g1[-2] if len(g1) >= 2 and finite(g1[-1]) and finite(g1[-2]) else float("nan")
        )
        values = [
            float(len(recent)),
            (t["event_date"] - valid[-1]["event_date"]).days if valid else float("nan"),
            (t["event_date"] - prior[-1]["event_date"]).days if prior else float("nan"),
            mean(s),
            mean(g1),
            mean(g3),
            mean([b - a for a, b in zip(s, g1, strict=True) if finite(a) and finite(b)]),
            float(finish_change),
            float(late_change),
            float(
                sum(
                    finite(a) and finite(b) and finite(c) for a, b, c in zip(s, g1, g3, strict=True)
                )
            ),
        ]
        output.append(dict(entry_id=t["entry_id"], **dict(zip(FEATURES, values, strict=True))))
        lineage.append(
            dict(
                entry_id=t["entry_id"],
                horse_id=horse,
                event_date=t["event_date"],
                cutoff_date=cutoff,
                window_start=start,
                latest_attempt_id=prior[-1]["entry_id"] if prior else None,
                latest_valid_id=valid[-1]["entry_id"] if valid else None,
                latest3_valid_ids=[r["entry_id"] for r in last3],
                valid365_ids=[r["entry_id"] for r in recent],
                max_source_date=prior[-1]["event_date"] if prior else None,
            )
        )
    return output, lineage
