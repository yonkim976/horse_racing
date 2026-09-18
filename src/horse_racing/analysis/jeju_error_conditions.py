"""Outcome-audit measurements, not predictor features or causal labels."""

import math


def number(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def delta(current, previous):
    a, b = number(current), number(previous)
    return a - b if a is not None and b is not None else None


def valid_rank(value, field):
    rank = number(value)
    return rank if rank is not None and rank.is_integer() and 1 <= rank <= field else None


def rank_quality(value, field):
    rank = valid_rank(value, field)
    return 1 - (rank - 1) / (field - 1) if rank is not None and field > 1 else None


def closing_quality(value, peers):
    value = number(value)
    peers = [number(x) for x in peers]
    peers = [x for x in peers if x is not None and x > 0]
    if value is None or value <= 0 or len(peers) < 2 or value not in peers:
        return None
    return (sum(x > value for x in peers) + 0.5 * (sum(x == value for x in peers) - 1)) / (
        len(peers) - 1
    )


def changed(a, b):
    return (
        float(str(a).strip() != str(b).strip())
        if a not in (None, "") and b not in (None, "")
        else None
    )


def threshold(value, bound, direction="le"):
    value = number(value)
    if value is None:
        return None
    return float(value <= bound if direction == "le" else value >= bound)


def flags(row):
    """Fixed descriptive thresholds; missing observations never mean no change."""
    return {
        "pre_burden_down_1kg": threshold(row.get("pre_burden_change_kg"), -1),
        "pre_easier_field_20elo": threshold(row.get("pre_rival_change_elo"), -20),
        "pre_distance_shorter": threshold(row.get("pre_distance_change_m"), -1),
        "pre_jockey_changed": row.get("pre_jockey_changed"),
        "pre_recent_poor_finish": threshold(row.get("pre_previous_finish_quality"), 0.25),
        "post_early_improved_025": threshold(row.get("post_early_vs_history"), 0.25, "ge"),
        "post_closing_improved_025": threshold(row.get("post_closing_vs_history"), 0.25, "ge"),
        "post_closing_worsened_025": threshold(row.get("post_closing_vs_history"), -0.25),
        "post_lost_3places_from_early": threshold(row.get("post_early_to_finish_gain"), -3),
        "post_bodyweight_abs_change_10kg": threshold(
            abs(row["post_bodyweight_change_kg"])
            if number(row.get("post_bodyweight_change_kg")) is not None
            else None,
            10,
            "ge",
        ),
    }
