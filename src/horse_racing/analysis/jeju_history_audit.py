"""Read-only attribution of missing historical section features."""

import math
from datetime import timedelta


def finite(value):
    try:
        return value is not None and not isinstance(value, bool) and math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def historical_rows(target, rows, cutoff_days=2):
    cutoff = target["event_date"] - timedelta(days=cutoff_days)
    return sorted(
        [
            r
            for r in rows
            if str(r["horse_id"]) == str(target["horse_id"]) and r["event_date"] <= cutoff
        ],
        key=lambda r: (r["event_date"], r["entry_id"]),
    )


def reconstruct_sections(prior):
    early = [
        float(r["early_rank"])
        for r in prior
        if finite(r.get("early_rank"))
        and finite(r.get("field_size"))
        and 1 <= float(r["early_rank"]) <= float(r["field_size"])
    ]
    closing = [
        float(r["closing_speed_quality"])
        for r in prior[-3:]
        if finite(r.get("closing_speed_quality"))
    ]
    return dict(
        historical_early_front_rate=sum(v <= 3 for v in early) / len(early) if early else None,
        closing_speed_quality_mean_3=sum(closing) / len(closing) if closing else None,
        history_count=len(prior),
        valid_early_count=len(early),
        valid_recent_closing_count=len(closing),
    )


def same_number(a, b):
    if not finite(a) and not finite(b):
        return True
    return finite(a) and finite(b) and abs(float(a) - float(b)) < 1e-12


def classify_missing(prior, source_prior, saved):
    rebuilt = reconstruct_sections(prior)
    names = ["historical_early_front_rate", "closing_speed_quality_mean_3"]
    matches = all(same_number(saved.get(k), rebuilt[k]) for k in names)
    missing = any(not finite(saved.get(k)) for k in names)
    codes = [r.get("finish_position") for r in source_prior]
    if not matches:
        reason = "feature_reconstruction_mismatch"
    elif not missing:
        reason = "observed"
    elif not prior and not source_prior:
        reason = "no_prior_race_row_in_available_sources"
    elif not prior and all(code in {93, 94, 95} for code in codes):
        reason = "only_prior_nonstarter_rows"
    elif not prior:
        reason = "prior_source_race_excluded_requires_review"
    else:
        reason = "prior_history_without_required_valid_sections"
    return {**rebuilt, "features_match": matches, "section_missing": missing, "reason": reason}
