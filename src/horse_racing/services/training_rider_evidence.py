"""Bind website rider evidence to an exact unchanged API training event."""

import hashlib
import json
from datetime import datetime


def training_fingerprint(row):
    values = [
        row.horse_id,
        row.meet_code,
        str(row.training_date_local),
        row.started_at_raw,
        row.ended_at_raw,
        row.duration_seconds,
        row.rider_type,
        row.rider_id,
    ]
    return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode()).hexdigest()


def training_event_key(row):
    try:
        start = datetime.strptime(row.started_at_raw, "%Y%m%d%H%M%S")
        end = datetime.strptime(row.ended_at_raw, "%Y%m%d%H%M%S")
    except (ValueError, TypeError):
        return None
    if start.date() != row.training_date_local or end.date() != row.training_date_local:
        return None
    if (end - start).total_seconds() != row.duration_seconds:
        return None
    return (
        row.training_date_local,
        start.strftime("%H:%M"),
        end.strftime("%H:%M"),
        row.duration_seconds,
    )
