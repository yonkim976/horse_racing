"""Prior race transitions with conservative within-calendar-year grade comparisons."""

from bisect import bisect_right
from collections import defaultdict
from datetime import timedelta

import numpy as np

BASIC = [
    "transition_previous_grade",
    "transition_grade_change",
    "transition_grade_up",
    "transition_6to5",
    "transition_distance_change_m",
    "transition_previous_finish_quality",
]
INTERACTIONS = [
    "transition_up_x_burden",
    "transition_6to5_x_burden",
    "transition_finish_x_burden",
    "transition_win_x_burden",
    "transition_finish_x_distance100",
    "transition_finish_x_pressure",
    "transition_up_x_finish",
]
FEATURES = BASIC + INTERACTIONS


def numeric(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return float("nan")
    return x if np.isfinite(x) else float("nan")


def grade(x):
    x = numeric(x)
    return x if np.isfinite(x) and x.is_integer() and 1 <= x <= 6 else float("nan")


def values(target, previous):
    nan = float("nan")
    if previous is None:
        return dict.fromkeys(FEATURES, nan)
    assert previous["event_date"] <= target["event_date"] - timedelta(days=2)
    assert str(previous["horse_id"]) == str(target["horse_id"])
    before = grade(previous.get("grade"))
    current = grade(target.get("declared_grade_number"))
    comparable = (
        previous["event_date"].year == target["event_date"].year
        and np.isfinite(before)
        and np.isfinite(current)
    )
    difference = current - before if comparable else nan
    up = float(difference < 0) if comparable else nan
    sixfive = float(before == 6 and current == 5) if comparable else nan
    distance = numeric(target.get("distance_m")) - numeric(previous.get("distance_m"))
    burden = numeric(target.get("declared_burden_kg")) - numeric(previous.get("burden_kg"))
    pressure = numeric(target.get("rival_early_pressure_count")) - numeric(
        previous.get("rival_early_pressure_count")
    )
    rank = numeric(previous.get("finish_position"))
    field = numeric(previous.get("field_size"))
    observed = (
        previous.get("outcome_status") == "normal_completed" and field > 1 and 1 <= rank <= field
    )
    quality = 1 - (rank - 1) / (field - 1) if observed else nan
    win = float(rank == 1) if observed else nan
    result = [
        before if comparable else nan,
        difference,
        up,
        sixfive,
        distance,
        quality,
        up * burden,
        sixfive * burden,
        quality * burden,
        win * burden,
        quality * distance / 100,
        quality * pressure,
        up * quality,
    ]
    return dict(zip(FEATURES, result, strict=True))


def build_features(targets, history):
    byhorse = defaultdict(list)
    for row in history:
        byhorse[str(row["horse_id"])].append(row)
    for rows in byhorse.values():
        rows.sort(key=lambda r: (r["event_date"], r["entry_id"]))
    dates = {k: [r["event_date"] for r in rows] for k, rows in byhorse.items()}
    output = []
    lineage = []
    for target in targets:
        key = str(target["horse_id"])
        cutoff = target["event_date"] - timedelta(days=2)
        rows = byhorse.get(key, [])
        index = bisect_right(dates.get(key, []), cutoff)
        prev = rows[index - 1] if index else None
        output.append(dict(entry_id=target["entry_id"], **values(target, prev)))
        lineage.append(
            dict(
                entry_id=target["entry_id"],
                horse_id=key,
                event_date=target["event_date"],
                cutoff_date=cutoff,
                previous_entry_id=prev["entry_id"] if prev else None,
                previous_date=prev["event_date"] if prev else None,
                crosses_year=prev["event_date"].year != target["event_date"].year if prev else None,
            )
        )
    return output, lineage
