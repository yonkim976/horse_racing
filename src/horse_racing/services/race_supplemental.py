from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from horse_racing.collectors.kra_api import (
    HORSE_EQUIPMENT_ENDPOINT,
    HORSE_EQUIPMENT_OPERATION,
    HORSE_GRADE_CHANGE_ENDPOINT,
    HORSE_GRADE_CHANGE_OPERATION,
    JOCKEY_CHANGE_ENDPOINT,
    JOCKEY_CHANGE_OPERATION,
    JUDGE_REPORT_ENDPOINT,
    JUDGE_REPORT_OPERATION,
    RACE_HORSE_CANCEL_ENDPOINT,
    RACE_HORSE_CANCEL_OPERATION,
    START_TRAINING_ENDPOINT,
    START_TRAINING_OPERATION,
    KraApiClient,
)
from horse_racing.db.models import (
    EntryEquipment,
    HorseGradeChange,
    HorseStartTraining,
    JockeyChange,
    Race,
    Racecourse,
    RaceEntry,
    RaceScratch,
    RaceStewardReport,
)
from horse_racing.parsers.race_supplemental import (
    EntryEquipmentItem,
    HorseGradeChangeItem,
    JockeyChangeItem,
    RaceScratchItem,
    StartTrainingItem,
    StewardReportItem,
)
from horse_racing.services.entry_sheet import IngestionSummary
from horse_racing.services.horse_history import _ingest_dataset, _now_ms, _upsert_horse
from horse_racing.services.race_day import DatasetDefinition


def ingest_jockey_changes(
    session: Session,
    client: KraApiClient,
    *,
    race_date: str,
    meet: int,
    raw_data_dir: Path,
    page_size: int = 1000,
) -> IngestionSummary:
    observed_at_ms = _now_ms()
    return _ingest_dataset(
        session,
        client,
        definition=DatasetDefinition(
            data_type="jockey_changes",
            source="data.go.kr/B551015/API10_1",
            endpoint=JOCKEY_CHANGE_ENDPOINT,
            operation=JOCKEY_CHANGE_OPERATION,
            public_params={"meet": meet, "rc_date": race_date, "_type": "json"},
        ),
        item_model=JockeyChangeItem,
        writer=lambda sess, _meet, items: _write_jockey_changes(sess, items, observed_at_ms),
        race_date=race_date,
        meet=meet,
        raw_data_dir=raw_data_dir,
        page_size=page_size,
    )


def ingest_scratches(
    session: Session,
    client: KraApiClient,
    *,
    race_date: str,
    meet: int,
    raw_data_dir: Path,
    page_size: int = 1000,
) -> IngestionSummary:
    observed_at_ms = _now_ms()
    return _ingest_dataset(
        session,
        client,
        definition=DatasetDefinition(
            data_type="race_scratches",
            source="data.go.kr/B551015/API9_1",
            endpoint=RACE_HORSE_CANCEL_ENDPOINT,
            operation=RACE_HORSE_CANCEL_OPERATION,
            public_params={"meet": meet, "rc_date": race_date, "_type": "json"},
        ),
        item_model=RaceScratchItem,
        writer=lambda sess, _meet, items: _write_scratches(sess, items, observed_at_ms),
        race_date=race_date,
        meet=meet,
        raw_data_dir=raw_data_dir,
        page_size=page_size,
    )


def ingest_equipment(
    session: Session,
    client: KraApiClient,
    *,
    race_date: str,
    meet: int,
    raw_data_dir: Path,
    page_size: int = 1000,
) -> IngestionSummary:
    observed_at_ms = _now_ms()
    return _ingest_dataset(
        session,
        client,
        definition=DatasetDefinition(
            data_type="entry_equipment",
            source="data.go.kr/B551015/API24_1",
            endpoint=HORSE_EQUIPMENT_ENDPOINT,
            operation=HORSE_EQUIPMENT_OPERATION,
            public_params={"meet": meet, "rc_date": race_date, "_type": "json"},
        ),
        item_model=EntryEquipmentItem,
        writer=lambda sess, _meet, items: _write_equipment(sess, items, observed_at_ms),
        race_date=race_date,
        meet=meet,
        raw_data_dir=raw_data_dir,
        page_size=page_size,
    )


def ingest_grade_changes(
    session: Session,
    client: KraApiClient,
    *,
    snapshot_date: str,
    meet: int | None,
    raw_data_dir: Path,
    page_size: int = 1000,
) -> IngestionSummary:
    observed_at_ms = _now_ms()
    public_params: dict[str, str | int] = {"_type": "json"}
    store_meet = meet if meet is not None else 0
    if meet is not None:
        public_params["meet"] = meet
    return _ingest_dataset(
        session,
        client,
        definition=DatasetDefinition(
            data_type="horse_grade_changes",
            source="data.go.kr/B551015/raceHorseRatingChangeInfo_2",
            endpoint=HORSE_GRADE_CHANGE_ENDPOINT,
            operation=HORSE_GRADE_CHANGE_OPERATION,
            public_params=public_params,
        ),
        item_model=HorseGradeChangeItem,
        writer=lambda sess, _meet, items: _write_grade_changes(sess, items, observed_at_ms),
        race_date=snapshot_date,
        meet=store_meet,
        raw_data_dir=raw_data_dir,
        page_size=page_size,
    )


def ingest_start_training(
    session: Session,
    client: KraApiClient,
    *,
    training_date: str,
    meet: int,
    raw_data_dir: Path,
    page_size: int = 1000,
) -> IngestionSummary:
    observed_at_ms = _now_ms()
    return _ingest_dataset(
        session,
        client,
        definition=DatasetDefinition(
            data_type="horse_start_training",
            source="data.go.kr/B551015/API22_1",
            endpoint=START_TRAINING_ENDPOINT,
            operation=START_TRAINING_OPERATION,
            public_params={"meet": meet, "tr_date": training_date, "_type": "json"},
        ),
        item_model=StartTrainingItem,
        writer=lambda sess, _meet, items: _write_start_training(sess, items, observed_at_ms),
        writer_with_sources=lambda sess, _meet, items, sources: _write_start_training(
            sess,
            items,
            observed_at_ms,
            item_sources=sources,
            expected_meet=meet,
            expected_date=training_date,
        ),
        race_date=training_date,
        meet=meet,
        raw_data_dir=raw_data_dir,
        page_size=page_size,
    )


def ingest_steward_reports(
    session: Session,
    client: KraApiClient,
    *,
    race_date: str,
    meet: int,
    raw_data_dir: Path,
    page_size: int = 1000,
) -> IngestionSummary:
    observed_at_ms = _now_ms()
    return _ingest_dataset(
        session,
        client,
        definition=DatasetDefinition(
            data_type="race_steward_reports",
            source="data.go.kr/B551015/API215",
            endpoint=JUDGE_REPORT_ENDPOINT,
            operation=JUDGE_REPORT_OPERATION,
            public_params={"meet": meet, "rc_date": race_date, "_type": "json"},
        ),
        item_model=StewardReportItem,
        writer=lambda sess, _meet, items: _write_steward_reports(sess, items, observed_at_ms),
        race_date=race_date,
        meet=meet,
        raw_data_dir=raw_data_dir,
        page_size=page_size,
    )


def _write_jockey_changes(
    session: Session,
    items: list[JockeyChangeItem],
    observed_at_ms: int,
) -> int:
    written = 0
    for item in items:
        horse = _upsert_horse(session, item.horse_id, item.horse_name)
        row = session.scalar(
            select(JockeyChange).where(
                JockeyChange.meet_code == item.meet_code,
                JockeyChange.race_date_local == item.race_date,
                JockeyChange.race_number == item.race_number,
                JockeyChange.horse_number == item.horse_number,
                JockeyChange.jockey_before_id == item.jockey_before_id,
                JockeyChange.jockey_after_id == item.jockey_after_id,
            )
        )
        if row is None:
            row = JockeyChange(
                meet_code=item.meet_code,
                race_date_local=item.race_date,
                race_number=item.race_number,
                horse_number=item.horse_number,
                jockey_before_id=item.jockey_before_id,
                jockey_after_id=item.jockey_after_id,
                observed_at_ms=observed_at_ms,
            )
            session.add(row)
        row.horse_id = horse.id
        row.jockey_before_name = item.jockey_before_name
        row.jockey_after_name = item.jockey_after_name
        row.carried_weight_before_kg = item.carried_weight_before_kg
        row.carried_weight_after_kg = item.carried_weight_after_kg
        row.reason = item.reason
        row.observed_at_ms = observed_at_ms
        written += 1
    return written


def _write_scratches(
    session: Session,
    items: list[RaceScratchItem],
    observed_at_ms: int,
) -> int:
    written = 0
    for item in items:
        horse = _upsert_horse(session, item.horse_id, item.horse_name)
        row = session.scalar(
            select(RaceScratch).where(
                RaceScratch.meet_code == item.meet_code,
                RaceScratch.race_date_local == item.race_date,
                RaceScratch.race_number == item.race_number,
                RaceScratch.horse_id == horse.id,
            )
        )
        if row is None:
            row = RaceScratch(
                horse_id=horse.id,
                meet_code=item.meet_code,
                race_date_local=item.race_date,
                race_number=item.race_number,
                observed_at_ms=observed_at_ms,
            )
            session.add(row)
        row.horse_number = item.horse_number
        row.reason = item.reason
        row.observed_at_ms = observed_at_ms
        _mark_entry_scratched(
            session,
            meet_code=item.meet_code,
            race_date=item.race_date,
            race_number=item.race_number,
            horse_id=horse.id,
        )
        written += 1
    return written


def _write_equipment(
    session: Session,
    items: list[EntryEquipmentItem],
    observed_at_ms: int,
) -> int:
    written = 0
    for item in items:
        horse = _upsert_horse(session, item.horse_id, item.horse_name)
        row = session.scalar(
            select(EntryEquipment).where(
                EntryEquipment.meet_code == item.meet_code,
                EntryEquipment.race_date_local == item.race_date,
                EntryEquipment.race_number == item.race_number,
                EntryEquipment.horse_number == item.horse_number,
            )
        )
        if row is None:
            row = EntryEquipment(
                meet_code=item.meet_code,
                race_date_local=item.race_date,
                race_number=item.race_number,
                horse_number=item.horse_number,
                observed_at_ms=observed_at_ms,
            )
            session.add(row)
        row.horse_id = horse.id
        row.equipment_raw = item.equipment_raw
        row.bleeding_count = item.bleeding_count
        row.bleeding_date_raw = item.bleeding_date_raw
        row.illness_note = item.illness_note
        row.observed_at_ms = observed_at_ms
        if item.equipment_raw:
            _update_entry_equipment(
                session,
                meet_code=item.meet_code,
                race_date=item.race_date,
                race_number=item.race_number,
                horse_id=horse.id,
                equipment_raw=item.equipment_raw,
            )
        written += 1
    return written


def _write_grade_changes(
    session: Session,
    items: list[HorseGradeChangeItem],
    observed_at_ms: int,
) -> int:
    written = 0
    for item in items:
        horse = _upsert_horse(session, item.horse_id, item.horse_name)
        row = session.scalar(
            select(HorseGradeChange).where(
                HorseGradeChange.horse_id == horse.id,
                HorseGradeChange.start_date_local == item.start_date,
                HorseGradeChange.grade_before == item.grade_before,
                HorseGradeChange.grade_after == item.grade_after,
            )
        )
        if row is None:
            row = HorseGradeChange(
                horse_id=horse.id,
                start_date_local=item.start_date,
                grade_before=item.grade_before,
                grade_after=item.grade_after,
                observed_at_ms=observed_at_ms,
            )
            session.add(row)
        row.meet_code = item.meet_code
        row.blood_type = item.blood_type
        row.end_date_local = item.end_date
        row.observed_at_ms = observed_at_ms
        if item.grade_after and item.end_date is None:
            horse.grade = item.grade_after
        written += 1
    return written


def _write_start_training(
    session: Session,
    items: list[StartTrainingItem],
    observed_at_ms: int,
    *,
    item_sources: list[tuple[int, int]] | None = None,
    expected_meet: int | None = None,
    expected_date: str | None = None,
) -> int:
    """Preserve multiplicity across all pages; repeat collection is idempotent.

    API22 has no event ID/time. occurrence_no is an anonymous storage slot.
    A verified website date is authoritative and is never overwritten by API22.
    Empty responses leave existing records intact.
    """
    if item_sources is not None and len(item_sources) != len(items):
        raise ValueError("출발조교 원문 위치 수가 입력 행 수와 다릅니다.")
    if any(
        (expected_meet is not None and item.meet_code != expected_meet)
        or (expected_date is not None and item.training_date.strftime("%Y%m%d") != expected_date)
        for item in items
    ):
        raise ValueError("출발조교 응답 지역·날짜가 요청 범위와 다릅니다.")
    groups = defaultdict(list)
    for index, item in enumerate(items):
        groups[(item.meet_code, item.training_date)].append((index, item))
    written = 0
    for (meet, day), incoming in groups.items():
        if session.bind.dialect.name == "postgresql":
            from sqlalchemy import text

            session.execute(
                text("SELECT pg_advisory_xact_lock(:key)"),
                {"key": meet * 100_000_000 + int(day.strftime("%Y%m%d"))},
            )
        existing = session.scalars(
            select(HorseStartTraining).where(
                HorseStartTraining.meet_code == meet,
                HorseStartTraining.training_date_local == day,
            )
        ).all()
        if any(row.source_kind == "kra_website" for row in existing):
            continue
        # An older concurrent collector must not roll back a newer snapshot.
        if existing and max(row.observed_at_ms for row in existing) > observed_at_ms:
            continue
        slots = {(row.horse_id, row.occurrence_no): row for row in existing}
        ordinals = defaultdict(int)
        retained = set()
        for index, item in incoming:
            horse = _upsert_horse(session, item.horse_id, item.horse_name)
            ordinals[horse.id] += 1
            slot = (horse.id, ordinals[horse.id])
            row = slots.get(slot)
            if row is None:
                row = HorseStartTraining(
                    horse_id=horse.id,
                    meet_code=meet,
                    training_date_local=day,
                    occurrence_no=slot[1],
                    observed_at_ms=observed_at_ms,
                )
                session.add(row)
            row.stable_part = item.stable_part
            row.stable_number = item.stable_number
            row.rider_name = item.rider_name
            row.remark = item.remark
            row.source_kind = "api22"
            row.source_document_id, row.source_row_no = (
                item_sources[index] if item_sources is not None else (None, None)
            )
            row.location_raw = None
            row.observed_at_ms = observed_at_ms
            retained.add(slot)
            written += 1
        # Replace only a nonempty, fully fetched date snapshot. Raw versions remain archived.
        for slot, row in slots.items():
            if slot not in retained:
                session.delete(row)
    return written


def _write_steward_reports(
    session: Session,
    items: list[StewardReportItem],
    observed_at_ms: int,
) -> int:
    written = 0
    for item in items:
        row = session.scalar(
            select(RaceStewardReport).where(
                RaceStewardReport.meet_code == item.meet_code,
                RaceStewardReport.race_date_local == item.race_date,
                RaceStewardReport.race_number == item.race_number,
            )
        )
        if row is None:
            row = RaceStewardReport(
                meet_code=item.meet_code,
                race_date_local=item.race_date,
                race_number=item.race_number,
                observed_at_ms=observed_at_ms,
            )
            session.add(row)
        row.weather = item.weather
        row.members = item.members
        row.judgement = item.judgement
        row.additional_judgement = item.additional_judgement
        row.jockey_change_note = item.jockey_change_note
        row.observed_at_ms = observed_at_ms
        written += 1
    return written


def _mark_entry_scratched(
    session: Session,
    *,
    meet_code: int,
    race_date,
    race_number: int,
    horse_id: int,
) -> None:
    entry = session.scalar(
        select(RaceEntry)
        .join(Race)
        .join(Racecourse)
        .where(
            Racecourse.kra_meet_code == meet_code,
            Race.race_date_local == race_date,
            Race.race_number == race_number,
            RaceEntry.horse_id == horse_id,
        )
    )
    if entry is not None:
        entry.scratched = True


def _update_entry_equipment(
    session: Session,
    *,
    meet_code: int,
    race_date,
    race_number: int,
    horse_id: int,
    equipment_raw: str,
) -> None:
    entry = session.scalar(
        select(RaceEntry)
        .join(Race)
        .join(Racecourse)
        .where(
            Racecourse.kra_meet_code == meet_code,
            Race.race_date_local == race_date,
            Race.race_number == race_number,
            RaceEntry.horse_id == horse_id,
        )
    )
    if entry is not None:
        entry.equipment = equipment_raw
