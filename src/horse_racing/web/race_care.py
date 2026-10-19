"""Collected pre-race training and clinic records for the declared field."""

from collections import defaultdict
from datetime import timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from horse_racing.db.models import (
    HorseMedical,
    HorseStartTraining,
    HorseTraining,
    Race,
    RaceEntry,
    RaceResult,
)
from horse_racing.services.medical_read import medical_display_filter
from horse_racing.services.training_read import (
    start_training_display_labels,
    training_display_fields,
)
from horse_racing.web.formatting import today_seoul

MAX_RECORDS_PER_HORSE = 100


def _records(session, model, date_column, horse_ids, beginning, through, *criteria):
    ranked = (
        select(
            model.id,
            func.row_number()
            .over(
                partition_by=model.horse_id,
                order_by=(date_column.desc(), model.id.desc()),
            )
            .label("rn"),
        )
        .where(
            model.horse_id.in_(horse_ids),
            date_column >= beginning,
            date_column <= through,
            *criteria,
        )
        .subquery()
    )
    return session.scalars(
        select(model)
        .join(ranked, ranked.c.id == model.id)
        .where(ranked.c.rn <= MAX_RECORDS_PER_HORSE)
        .order_by(date_column.desc(), model.id.desc())
    ).all()


def _duration(seconds):
    if seconds is None:
        return "—"
    minutes, remainder = divmod(seconds, 60)
    return " ".join(
        part
        for part in (
            f"{minutes}분" if minutes else "",
            f"{remainder}초" if remainder or not minutes else "",
        )
        if part
    )


def load_race_care(session: Session, race: Race) -> dict | None:
    if race.status != "scheduled":
        return None
    today = today_seoul()
    through = min(today, race.race_date_local - timedelta(days=1))
    training_start = race.race_date_local - timedelta(days=28)
    medical_start = race.race_date_local - timedelta(days=90)
    horse_ids = {entry.horse_id for entry in race.entries}
    training, starts, medical = defaultdict(list), defaultdict(list), defaultdict(list)
    last_starts = {}
    if horse_ids:
        last_starts = dict(
            session.execute(
                select(RaceEntry.horse_id, func.max(Race.race_date_local))
                .join(Race, Race.id == RaceEntry.race_id)
                .join(RaceResult, RaceResult.race_entry_id == RaceEntry.id)
                .where(
                    RaceEntry.horse_id.in_(horse_ids),
                    Race.race_date_local < race.race_date_local,
                    Race.race_date_local <= today,
                    Race.status != "cancelled",
                    RaceEntry.scratched.is_(False),
                    or_(
                        RaceResult.finish_position.between(1, 89),
                        RaceResult.finish_position.in_((93, 96)),
                        RaceResult.disqualified.is_(True),
                    ),
                )
                .group_by(RaceEntry.horse_id)
            ).all()
        )
        daily_records = _records(
            session,
            HorseTraining,
            HorseTraining.training_date_local,
            horse_ids,
            training_start,
            through,
        )
        displays = training_display_fields(session, daily_records)
        for row in daily_records:
            display = displays[row.id]
            training[row.horse_id].append(
                {
                    "date": row.training_date_local.isoformat(),
                    "duration": _duration(row.duration_seconds),
                    "canter": display["canter_count_display"],
                    "gallop": display["gallop_count_display"],
                    "rider_type": row.rider_type or "—",
                    **display,
                }
            )
        start_records = _records(
            session,
            HorseStartTraining,
            HorseStartTraining.training_date_local,
            horse_ids,
            training_start,
            through,
        )
        start_labels = start_training_display_labels(session, start_records)
        for row in start_records:
            starts[row.horse_id].append(
                {
                    "date": row.training_date_local.isoformat(),
                    "rider": start_labels[row.id],
                    "remark": row.remark or "—",
                    "location": row.location_raw or "—",
                }
            )
        for row in _records(
            session,
            HorseMedical,
            HorseMedical.clinic_date_local,
            horse_ids,
            medical_start,
            through,
            medical_display_filter(),
        ):
            medical[row.horse_id].append(
                {
                    "date": row.clinic_date_local.isoformat(),
                    "hospital": row.hospital_name or "—",
                    "diagnosis": " · ".join(
                        part for part in (row.diagnosis_1, row.diagnosis_2) if part
                    )
                    or "—",
                }
            )
    horses = []
    for entry in sorted(race.entries, key=lambda entry: entry.horse_number):
        daily, start, clinics = (
            training[entry.horse_id],
            starts[entry.horse_id],
            medical[entry.horse_id],
        )
        dates = [row["date"] for row in daily + start]
        horses.append(
            {
                "number": entry.horse_number,
                "horse_id": entry.horse.kra_horse_id,
                "name": entry.horse.name_ko,
                "scratched": entry.scratched,
                "last_start_date": (
                    last_starts[entry.horse_id].isoformat()
                    if entry.horse_id in last_starts
                    else None
                ),
                "scheduled_date": (
                    race.race_date_local.isoformat()
                    if not entry.scratched and race.race_date_local >= today
                    else None
                ),
                "training": daily,
                "starts": start,
                "medical": clinics,
                "training_days": len({row["date"] for row in daily}),
                "latest_training": max(dates) if dates else None,
                "latest_medical": clinics[0]["date"] if clinics else None,
            }
        )
    return {
        "training_start": training_start.isoformat(),
        "medical_start": medical_start.isoformat(),
        "through": through.isoformat(),
        "limit": MAX_RECORDS_PER_HORSE,
        "horses": horses,
    }
