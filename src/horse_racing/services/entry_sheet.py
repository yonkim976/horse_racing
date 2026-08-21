from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import date, datetime
from datetime import time as datetime_time
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from horse_racing.collectors.kra_api import KraApiClient
from horse_racing.db.models import (
    Horse,
    IngestionRun,
    Jockey,
    Owner,
    Race,
    Racecourse,
    RaceEntry,
    SourceDocument,
    Trainer,
)
from horse_racing.parsers.entry_sheet import EntrySheetItem, parse_entry_sheet_page
from horse_racing.services.raw_store import store_entry_sheet_page

MEET_METADATA = {
    1: ("SEOUL", "서울"),
    2: ("JEJU", "제주"),
    3: ("BUSAN_GYEONGNAM", "부산경남"),
    4: ("YEONGCHEON", "영천"),
}


@dataclass(frozen=True, slots=True)
class IngestionSummary:
    run_id: int
    pages: int
    records_fetched: int
    records_written: int


def ingest_entry_sheet(
    session: Session,
    client: KraApiClient,
    *,
    race_date: str,
    meet: int,
    raw_data_dir: Path,
    page_size: int = 100,
) -> IngestionSummary:
    run = IngestionRun(
        source="data.go.kr/B551015/API26_2",
        data_type="entry_sheet",
        started_at_ms=_now_ms(),
        status="running",
    )
    session.add(run)
    session.commit()
    run_id = run.id

    parsed_items: list[EntrySheetItem] = []
    pages = 0
    try:
        for fetched in client.iter_entry_sheet_pages(
            race_date=race_date,
            meet=meet,
            page_size=page_size,
        ):
            page_no = int(fetched.public_params["pageNo"])
            stored = store_entry_sheet_page(
                fetched,
                raw_data_dir=raw_data_dir,
                race_date=race_date,
                meet=meet,
                run_id=run_id,
                page_no=page_no,
            )
            session.add(
                SourceDocument(
                    ingestion_run_id=run_id,
                    source_url=fetched.source_url,
                    endpoint=fetched.endpoint,
                    operation=fetched.operation,
                    request_params_json=json.dumps(
                        fetched.public_params,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    requested_at_ms=fetched.requested_at_ms,
                    retrieved_at_ms=fetched.retrieved_at_ms,
                    http_status_code=fetched.status_code,
                    content_type=fetched.content_type,
                    response_bytes=len(fetched.body),
                    local_path=str(stored.path),
                    sha256=stored.sha256,
                )
            )
            pages += 1
            session.commit()

            parsed_page = parse_entry_sheet_page(fetched.payload)
            parsed_items.extend(parsed_page.items)
            run.records_fetched = len(parsed_items)
            session.commit()

        records_written = _upsert_items(session, meet=meet, items=parsed_items)
        run.status = "completed"
        run.completed_at_ms = _now_ms()
        run.records_written = records_written
        session.commit()
        return IngestionSummary(
            run_id=run_id,
            pages=pages,
            records_fetched=len(parsed_items),
            records_written=records_written,
        )
    except Exception as exc:
        session.rollback()
        failed_run = session.get(IngestionRun, run_id)
        if failed_run is not None:
            failed_run.status = "failed"
            failed_run.completed_at_ms = _now_ms()
            failed_run.error_message = str(exc)
            session.commit()
        raise


def _upsert_items(session: Session, *, meet: int, items: list[EntrySheetItem]) -> int:
    racecourse = _upsert_racecourse(session, meet)
    records_written = 0
    for item in items:
        race = _upsert_race(session, racecourse, item)
        horse = _upsert_horse(session, item)
        jockey = _upsert_person(
            session,
            Jockey,
            "kra_jockey_id",
            item.jockey_id,
            item.jockey_name,
            item.jockey_name_en,
        )
        trainer = _upsert_person(
            session,
            Trainer,
            "kra_trainer_id",
            item.trainer_id,
            item.trainer_name,
            item.trainer_name_en,
        )
        owner = _upsert_person(
            session,
            Owner,
            "kra_owner_id",
            item.owner_id,
            item.owner_name,
            item.owner_name_en,
        )
        session.flush()

        entry = session.scalar(
            select(RaceEntry).where(
                RaceEntry.race_id == race.id,
                RaceEntry.horse_id == horse.id,
            )
        )
        if entry is None:
            entry = session.scalar(
                select(RaceEntry).where(
                    RaceEntry.race_id == race.id,
                    RaceEntry.horse_number == item.horse_number,
                )
            )
            if entry is None:
                entry = RaceEntry(race=race, horse=horse, horse_number=item.horse_number)
                session.add(entry)
            else:
                entry.horse = horse
        entry.horse_number = item.horse_number
        entry.carried_weight_kg = item.carried_weight_kg
        entry.rating = item.rating
        entry.jockey = jockey
        entry.trainer = trainer
        entry.owner = owner
        entry.scratched = False
        records_written += 1
    return records_written


def _upsert_racecourse(session: Session, meet: int) -> Racecourse:
    try:
        code, name_ko = MEET_METADATA[meet]
    except KeyError as exc:
        raise ValueError(f"지원하지 않는 경마장 코드입니다: {meet}") from exc
    racecourse = session.scalar(select(Racecourse).where(Racecourse.kra_meet_code == meet))
    if racecourse is None:
        racecourse = Racecourse(kra_meet_code=meet, code=code, name_ko=name_ko)
        session.add(racecourse)
    else:
        racecourse.code = code
        racecourse.name_ko = name_ko
    session.flush()
    return racecourse


def _upsert_race(session: Session, racecourse: Racecourse, item: EntrySheetItem) -> Race:
    race = session.scalar(
        select(Race).where(
            Race.racecourse_id == racecourse.id,
            Race.race_date_local == item.race_date,
            Race.race_number == item.race_number,
        )
    )
    if race is None:
        race = Race(
            racecourse=racecourse,
            race_date_local=item.race_date,
            race_number=item.race_number,
            distance_m=item.distance_m,
        )
        session.add(race)
    race.distance_m = item.distance_m
    if item.grade:
        race.grade = item.grade
    if item.race_name:
        race.race_name = item.race_name
    if scheduled_at_ms := _scheduled_at_ms(item.race_date, item.scheduled_time):
        race.scheduled_at_ms = scheduled_at_ms
    if race.status != "completed":
        race.status = "scheduled"
    session.flush()
    return race


def _upsert_horse(session: Session, item: EntrySheetItem) -> Horse:
    horse = session.scalar(select(Horse).where(Horse.kra_horse_id == item.horse_id))
    if horse is None:
        horse = Horse(kra_horse_id=item.horse_id, name_ko=item.horse_name)
        session.add(horse)
    horse.name_ko = item.horse_name
    if item.horse_name_en:
        horse.name_en = item.horse_name_en
    if item.sex:
        horse.sex = item.sex
    if item.origin_country:
        horse.origin_country = item.origin_country
    session.flush()
    return horse


def _upsert_person(
    session: Session,
    model: type[Jockey] | type[Trainer] | type[Owner],
    id_attribute: str,
    kra_id: str | None,
    name_ko: str | None,
    name_en: str | None,
) -> Jockey | Trainer | Owner | None:
    if not kra_id:
        return None
    id_column = getattr(model, id_attribute)
    person = session.scalar(select(model).where(id_column == kra_id))
    if person is None:
        person = model(**{id_attribute: kra_id, "name_ko": name_ko or kra_id})
        session.add(person)
    person.name_ko = name_ko or person.name_ko
    if name_en:
        person.name_en = name_en
    return person


def _scheduled_at_ms(race_date: date, scheduled_time: str | None) -> int | None:
    if not scheduled_time:
        return None
    digits = "".join(character for character in scheduled_time if character.isdigit())
    if len(digits) not in {3, 4}:
        return None
    digits = digits.zfill(4)
    try:
        local_time = datetime_time(hour=int(digits[:2]), minute=int(digits[2:]))
    except ValueError:
        return None
    local_datetime = datetime.combine(
        race_date,
        local_time,
        tzinfo=ZoneInfo("Asia/Seoul"),
    )
    return int(local_datetime.timestamp() * 1000)


def _now_ms() -> int:
    return time.time_ns() // 1_000_000
