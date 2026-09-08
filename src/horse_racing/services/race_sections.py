from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from horse_racing.collectors.kra_api import (
    RACE_RESULT_WITH_SECTIONS_ENDPOINT,
    RACE_RESULT_WITH_SECTIONS_OPERATION,
    KraApiClient,
    response_body,
)
from horse_racing.db.models import (
    IngestionRun,
    Race,
    Racecourse,
    RaceEntry,
    RaceResult,
    RaceSectionResult,
    SourceDocument,
)
from horse_racing.parsers.race_day import parse_items
from horse_racing.parsers.race_section import (
    ParsedSectionValue,
    RaceResultSectionItem,
    parse_section_values,
)
from horse_racing.services.entry_sheet import IngestionSummary, _upsert_racecourse
from horse_racing.services.race_day import _find_race
from horse_racing.services.raw_store import store_kra_page


def section_data_exists(
    client: KraApiClient,
    *,
    race_date: str,
    meet: int,
) -> bool:
    fetched = next(
        client.iter_pages(
            endpoint=RACE_RESULT_WITH_SECTIONS_ENDPOINT,
            operation=RACE_RESULT_WITH_SECTIONS_OPERATION,
            public_params={"meet": meet, "rc_date": race_date, "_type": "json"},
            page_size=1,
            service_key_parameter="ServiceKey",
        )
    )
    body = response_body(fetched.payload)
    try:
        return int(body.get("totalCount") or 0) > 0
    except (TypeError, ValueError):
        return False


# KRA special finish codes (경주제외/출전취소/주행중지/경주취소 등).
# Real finishers use 1..field_size; codes >= 90 are non-racing outcomes.
MAX_FINISH_POSITION_FOR_SECTIONS = 89


def section_day_is_stored(
    session: Session,
    *,
    race_date: date,
    meet: int,
) -> bool:
    """Return True when every expected finisher has an S1F section row.

    Expected finishers are completed-race result entries whose finish_position
    is missing or a normal placing (<= 89). Special KRA codes (>= 90) such as
    경주제외/출전취소/주행중지/경주취소 are ignored because API4_3 does not
    provide section times for them.
    """
    expected_filter = (
        RaceResult.finish_position.is_(None)
        | (RaceResult.finish_position <= MAX_FINISH_POSITION_FOR_SECTIONS)
    )
    expected_entry_count = session.scalar(
        select(func.count())
        .select_from(RaceEntry)
        .join(RaceEntry.race)
        .join(Race.racecourse)
        .join(RaceEntry.result)
        .where(
            Race.race_date_local == race_date,
            Racecourse.kra_meet_code == meet,
            Race.status == "completed",
            expected_filter,
        )
    )
    if not expected_entry_count:
        return True

    covered_entry_count = session.scalar(
        select(func.count(func.distinct(RaceSectionResult.race_entry_id)))
        .select_from(RaceSectionResult)
        .join(RaceSectionResult.race_entry)
        .join(RaceEntry.race)
        .join(Race.racecourse)
        .join(RaceEntry.result)
        .where(
            Race.race_date_local == race_date,
            Racecourse.kra_meet_code == meet,
            RaceSectionResult.section_code == "S1F",
            expected_filter,
        )
    )
    return int(covered_entry_count or 0) >= int(expected_entry_count or 0)


def ingest_race_sections(
    session: Session,
    client: KraApiClient,
    *,
    race_date: str,
    meet: int,
    raw_data_dir: Path,
    page_size: int = 1000,
) -> IngestionSummary:
    return _ingest_dataset(
        session,
        client,
        definition=_section_dataset_definition(race_date, meet),
        item_model=RaceResultSectionItem,
        writer=_write_section_results,
        race_date=race_date,
        meet=meet,
        raw_data_dir=raw_data_dir,
        page_size=page_size,
    )


def _section_dataset_definition(race_date: str, meet: int):
    from horse_racing.services.race_day import DatasetDefinition

    return DatasetDefinition(
        data_type="race_result_sections",
        source="data.go.kr/B551015/API4_3",
        endpoint=RACE_RESULT_WITH_SECTIONS_ENDPOINT,
        operation=RACE_RESULT_WITH_SECTIONS_OPERATION,
        public_params={"meet": meet, "rc_date": race_date, "_type": "json"},
    )


def _write_section_results(
    session: Session,
    meet: int,
    items: list[RaceResultSectionItem],
) -> int:
    racecourse = _upsert_racecourse(session, meet)
    records_written = 0
    for item in items:
        race = _find_race(session, racecourse, item.race_date, item.race_number)
        if race is None:
            continue
        entry = _find_entry(session, race, item)
        if entry is None:
            continue
        for section in parse_section_values(item, meet):
            _upsert_section_result(session, entry, section)
            records_written += 1
    return records_written


def _find_entry(session: Session, race: Race, item: RaceResultSectionItem) -> RaceEntry | None:
    entry = session.scalar(
        select(RaceEntry).where(
            RaceEntry.race_id == race.id,
            RaceEntry.horse_number == item.horse_number,
        )
    )
    if entry is not None:
        return entry
    return session.scalar(
        select(RaceEntry)
        .join(RaceEntry.horse)
        .where(RaceEntry.race_id == race.id, RaceEntry.horse.has(kra_horse_id=item.horse_id))
    )


def _upsert_section_result(
    session: Session,
    entry: RaceEntry,
    section: ParsedSectionValue,
) -> None:
    row = session.scalar(
        select(RaceSectionResult).where(
            RaceSectionResult.race_entry_id == entry.id,
            RaceSectionResult.section_code == section.section_code,
        )
    )
    if row is None:
        row = RaceSectionResult(
            race_entry=entry,
            section_code=section.section_code,
        )
        session.add(row)
    row.elapsed_time_ms = section.elapsed_time_ms
    row.position = section.position


def _ingest_dataset[ItemT: BaseModel](
    session: Session,
    client: KraApiClient,
    *,
    definition,
    item_model: type[ItemT],
    writer,
    race_date: str,
    meet: int,
    raw_data_dir: Path,
    page_size: int,
) -> IngestionSummary:
    run = IngestionRun(
        source=definition.source,
        data_type=definition.data_type,
        started_at_ms=_now_ms(),
        status="running",
    )
    session.add(run)
    session.commit()
    run_id = run.id

    parsed_items: list[ItemT] = []
    pages = 0
    try:
        for fetched in client.iter_pages(
            endpoint=definition.endpoint,
            operation=definition.operation,
            public_params=definition.public_params,
            page_size=page_size,
            service_key_parameter="ServiceKey",
        ):
            page_no = int(fetched.public_params["pageNo"])
            stored = store_kra_page(
                fetched,
                raw_data_dir=raw_data_dir,
                data_type=definition.data_type,
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
            parsed_items.extend(parse_items(fetched.payload, item_model))
            pages += 1
            run.records_fetched = len(parsed_items)
            session.commit()

        records_written = writer(session, meet, parsed_items)
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


def _now_ms() -> int:
    return time.time_ns() // 1_000_000
