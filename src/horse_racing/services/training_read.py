"""Presentation-only daily training fields; never rewrite source observations.

Keep these rules aligned with public.horse_training_serving. A jockey-number
reference identifies a name, not independently verified riding at every event.
Starting training uses explicit source markers or an official jockey-name reference;
an unmarked, unmatched name does not establish a role.
"""

import re

from sqlalchemy import select

from horse_racing.db.models import HorseTrainingRiderObservation, Jockey
from horse_racing.services.training_rider_evidence import training_fingerprint

_START_MARKERS = {
    "조": "조교사",
    "관": "주로조교",
    "생": "교육생",
    "후": "기수후보생",
    "트": "기수트랙라이더",
}
_START_ROLES = {
    "기수",
    "조교사",
    "조교보",
    "조교승인",
    "기수후보생",
    "교육생",
    "주로조교",
    "기수트랙라이더",
}


def start_training_display_labels(session, records):
    """Only show personal names for jockeys; preserve explicit non-jockey roles."""
    records = list(records)
    roles, candidates = {}, {}
    for row in records:
        raw = (row.rider_name or "").strip()
        marker = re.fullmatch(r".*\((조|관|생|후|트)\)", raw)
        role = _START_MARKERS.get(raw) or (_START_MARKERS[marker[1]] if marker else None)
        if role or raw in _START_ROLES:
            roles[row.id] = role or raw
        elif raw not in ("", "-", "—", "외"):
            candidates[row.id] = raw
    names = sorted(set(candidates.values()))
    jockey_names = set()
    for start in range(0, len(names), 500):
        jockey_names.update(
            session.scalars(
                select(Jockey.name_ko).where(Jockey.name_ko.in_(names[start : start + 500]))
            )
        )
    return {
        row.id: roles.get(row.id)
        or (candidates[row.id] if candidates.get(row.id) in jockey_names else "미확인")
        for row in records
    }


def training_display_fields(session, records):
    records = list(records)
    observations = {}
    ids = [r.id for r in records]
    for start in range(0, len(ids), 500):
        observations.update(
            (o.horse_training_id, o)
            for o in session.scalars(
                select(HorseTrainingRiderObservation).where(
                    HorseTrainingRiderObservation.horse_training_id.in_(ids[start : start + 500])
                )
            )
        )
    numbers = sorted({r.rider_id for r in records if r.rider_type == "기수" and r.rider_id})
    names = {}
    for start in range(0, len(numbers), 500):
        names.update(
            session.execute(
                select(Jockey.kra_jockey_id, Jockey.name_ko).where(
                    Jockey.kra_jockey_id.in_(numbers[start : start + 500])
                )
            ).all()
        )
    result = {}
    for row in records:
        name = names.get(row.rider_id) if row.rider_type == "기수" else None
        name = name.strip() if name and name.strip() not in ("", "-") else None
        role = (row.rider_type or "").strip()
        missing_role = role in ("", "-")
        missing_counts = row.meet_code == 2 and row.canter_count == 0 and row.gallop_count == 0
        result[row.id] = {
            "rider_name": name,
            "rider_display_label": name or ("미확인" if missing_role else role),
            "rider_identity_status": (
                "official_id_reference"
                if name
                else "jockey_name_unresolved"
                if role == "기수"
                else "not_available"
                if missing_role
                else "role_only"
            ),
            "canter_count_display": None if missing_counts else row.canter_count,
            "gallop_count_display": None if missing_counts else row.gallop_count,
            "counts_availability_status": "not_available" if missing_counts else "source_values",
            "rider_source_note": "API 기승자 구분과 공식 번호 기준",
        }
        observation = observations.get(row.id)
        if observation and observation.source_fingerprint == training_fingerprint(row):
            is_jockey = observation.rider_role == "기수"
            result[row.id].update(
                rider_name=observation.jockey_name if is_jockey else None,
                rider_display_label=(observation.jockey_name or "기수")
                if is_jockey
                else observation.rider_role,
                rider_identity_status="website_same_event",
                rider_source_note="공식 홈페이지의 동일 말·날짜·입퇴장 시각·조교 시간 대조",
            )
    return result
