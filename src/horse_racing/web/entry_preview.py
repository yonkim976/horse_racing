from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from horse_racing.db.models import EntryEquipment, HorseTraining, Race, RaceEntry, RaceResult


@dataclass(frozen=True, slots=True)
class EntryPreview:
    previous_date: date | None = None
    weight_delta: float | None = None
    equipment: str = "—"
    training_count: int | None = None


def month_before(day: date) -> date:
    year, month = (day.year, day.month - 1) if day.month > 1 else (day.year - 1, 12)
    return date(year, month, min(day.day, monthrange(year, month)[1]))


def load_entry_previews(session: Session, race: Race) -> dict[int, EntryPreview]:
    """Batch current equipment and pre-race history, without looking past race day."""
    if race.status in {"completed", "cancelled"} or not race.entries:
        return {}
    horse_ids = [entry.horse_id for entry in race.entries]
    ranked = (
        select(
            RaceEntry.horse_id.label("horse_id"),
            Race.race_date_local.label("day"),
            RaceEntry.carried_weight_kg.label("weight"),
            func.row_number().over(
                partition_by=RaceEntry.horse_id,
                order_by=(Race.race_date_local.desc(), Race.race_number.desc(), Race.id.desc()),
            ).label("recency"),
        )
        .join(Race, Race.id == RaceEntry.race_id)
        .join(RaceResult, RaceResult.race_entry_id == RaceEntry.id)
        .where(
            RaceEntry.horse_id.in_(horse_ids),
            Race.race_date_local < race.race_date_local,
            Race.status != "cancelled",
            RaceEntry.scratched.is_(False),
            or_(
                RaceResult.finish_position.between(1, 89),
                RaceResult.finish_position.in_((93, 96)),
                RaceResult.disqualified.is_(True),
            ),
        )
    ).subquery()
    previous = {
        row.horse_id: row for row in session.execute(
            select(ranked.c.horse_id, ranked.c.day, ranked.c.weight)
            .where(ranked.c.recency == 1)
        )
    }
    training = dict(session.execute(
        select(HorseTraining.horse_id, func.count(HorseTraining.id))
        .where(
            HorseTraining.horse_id.in_(horse_ids),
            HorseTraining.training_date_local >= month_before(race.race_date_local),
            HorseTraining.training_date_local < race.race_date_local,
        )
        .group_by(HorseTraining.horse_id)
    ).all())
    equipment_rows = session.scalars(select(EntryEquipment).where(
        EntryEquipment.meet_code == race.racecourse.kra_meet_code,
        EntryEquipment.race_date_local == race.race_date_local,
        EntryEquipment.race_number == race.race_number,
    )).all()
    equipment_by_horse = {row.horse_id: row for row in equipment_rows if row.horse_id is not None}
    equipment_by_number = {
        row.horse_number: row for row in equipment_rows if row.horse_id is None
    }
    output = {}
    for entry in race.entries:
        prior = previous.get(entry.horse_id)
        delta = None
        if prior is not None and prior.weight is not None and entry.carried_weight_kg is not None:
            delta = round(entry.carried_weight_kg - prior.weight, 2)
        equipment = equipment_by_horse.get(entry.horse_id)
        if equipment is None:
            equipment = equipment_by_number.get(entry.horse_number)
        equipment_label = entry.equipment_card_raw
        if equipment_label is None:
            equipment_label = entry.equipment
        if equipment_label is None and equipment is not None:
            equipment_label = equipment.equipment_raw or ""
        if equipment_label is not None:
            equipment_label = equipment_label.strip()
            if equipment_label in {"", "-", "—"}:
                equipment_label = "없음"
        output[entry.horse_id] = EntryPreview(
            previous_date=prior.day if prior is not None else None,
            weight_delta=delta,
            equipment=equipment_label if equipment_label is not None else "—",
            training_count=training.get(entry.horse_id),
        )
    return output
