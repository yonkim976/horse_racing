"""Collected pre-race training and clinic records for the declared field."""

from collections import defaultdict
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from horse_racing.db.models import HorseMedical, HorseStartTraining, HorseTraining, Race
from horse_racing.web.formatting import today_seoul


MAX_RECORDS_PER_HORSE = 100


def _records(session, model, date_column, horse_ids, beginning, through):
    ranked = (
        select(
            model.id,
            func.row_number().over(
                partition_by=model.horse_id,
                order_by=(date_column.desc(), model.id.desc()),
            ).label("rn"),
        )
        .where(model.horse_id.in_(horse_ids), date_column >= beginning, date_column <= through)
        .subquery()
    )
    return session.scalars(
        select(model).join(ranked, ranked.c.id == model.id)
        .where(ranked.c.rn <= MAX_RECORDS_PER_HORSE)
        .order_by(date_column.desc(), model.id.desc())
    ).all()


def _duration(seconds):
    if seconds is None:
        return "—"
    minutes, remainder = divmod(seconds, 60)
    return " ".join(part for part in (
        f"{minutes}분" if minutes else "",
        f"{remainder}초" if remainder or not minutes else "",
    ) if part)


def load_race_care(session: Session, race: Race) -> dict | None:
    if race.status != "scheduled":
        return None
    through = min(today_seoul(), race.race_date_local - timedelta(days=1))
    training_start = race.race_date_local - timedelta(days=28)
    medical_start = race.race_date_local - timedelta(days=90)
    horse_ids = {entry.horse_id for entry in race.entries}
    training, starts, medical = defaultdict(list), defaultdict(list), defaultdict(list)
    if horse_ids:
        for row in _records(session, HorseTraining, HorseTraining.training_date_local,
                            horse_ids, training_start, through):
            training[row.horse_id].append({
                "date": row.training_date_local.isoformat(),
                "duration": _duration(row.duration_seconds),
                "canter": row.canter_count,
                "gallop": row.gallop_count,
                "trainer": row.trainer_name or "—",
                "rider_type": row.rider_type or "—",
            })
        for row in _records(session, HorseStartTraining, HorseStartTraining.training_date_local,
                            horse_ids, training_start, through):
            starts[row.horse_id].append({
                "date": row.training_date_local.isoformat(),
                "rider": row.rider_name or "—",
                "remark": row.remark or "—",
                "location": row.location_raw or "—",
            })
        for row in _records(session, HorseMedical, HorseMedical.clinic_date_local,
                            horse_ids, medical_start, through):
            medical[row.horse_id].append({
                "date": row.clinic_date_local.isoformat(),
                "hospital": row.hospital_name or "—",
                "diagnosis": " · ".join(part for part in (row.diagnosis_1, row.diagnosis_2) if part) or "—",
            })
    horses = []
    for entry in sorted(race.entries, key=lambda entry: entry.horse_number):
        daily, start, clinics = training[entry.horse_id], starts[entry.horse_id], medical[entry.horse_id]
        dates = [row["date"] for row in daily + start]
        horses.append({
            "number": entry.horse_number,
            "horse_id": entry.horse.kra_horse_id,
            "name": entry.horse.name_ko,
            "scratched": entry.scratched,
            "training": daily,
            "starts": start,
            "medical": clinics,
            "training_days": len({row["date"] for row in daily}),
            "latest_training": max(dates) if dates else None,
            "latest_medical": clinics[0]["date"] if clinics else None,
        })
    return {
        "training_start": training_start.isoformat(),
        "medical_start": medical_start.isoformat(),
        "through": through.isoformat(),
        "limit": MAX_RECORDS_PER_HORSE,
        "horses": horses,
    }
