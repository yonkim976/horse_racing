from __future__ import annotations

import json
import re
import time
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from horse_racing.collectors.kra_api import KraApiClient
from horse_racing.db.models import (
    EntryEquipmentChange,
    IngestionRun,
    Race,
    Racecourse,
    RaceEntry,
    SourceDocument,
)
from horse_racing.parsers.gate_entry_sheet import (
    GateEntrySheetItem,
    parse_equipment_changes,
    parse_gate_entry_sheet_page,
)
from horse_racing.services.raw_store import store_kra_page


@dataclass(frozen=True, slots=True)
class GateIngestionSummary:
    run_id: int
    pages: int
    records_fetched: int
    records_written: int


def ingest_gate_numbers(
    session: Session,
    client: KraApiClient,
    *,
    race_date: str,
    meet: int,
    raw_data_dir: Path,
    page_size: int = 1000,
) -> GateIngestionSummary:
    """Collect API78 ``gtno`` and verify it against the stored entry number."""
    run = IngestionRun(
        source="data.go.kr/B551015/API78",
        data_type="gate_entry_sheet",
        started_at_ms=_now_ms(),
        status="running",
    )
    session.add(run)
    session.commit()
    run_id = run.id

    parsed_items: list[GateEntrySheetItem] = []
    latest_observed_at_ms = 0
    pages = 0
    try:
        for fetched in client.iter_gate_entry_sheet_pages(
            race_date=race_date,
            meet=meet,
            page_size=page_size,
        ):
            page_no = int(fetched.public_params["pageNo"])
            stored = store_kra_page(
                fetched,
                raw_data_dir=raw_data_dir,
                data_type="gate_entry_sheet",
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
            parsed = parse_gate_entry_sheet_page(fetched.payload)
            parsed_items.extend(parsed.items)
            latest_observed_at_ms = max(latest_observed_at_ms, fetched.retrieved_at_ms)
            pages += 1
            run.records_fetched = len(parsed_items)
            session.commit()

        records_written = _write_gate_numbers(
            session,
            meet=meet,
            items=parsed_items,
            observed_at_ms=latest_observed_at_ms,
        )
        run.status = "completed"
        run.completed_at_ms = _now_ms()
        run.records_written = records_written
        session.commit()
        return GateIngestionSummary(
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


def gate_numbers_are_complete(session: Session, *, race_date: date, meet: int) -> bool:
    race_ids = select(Race.id).join(Racecourse).where(
        Racecourse.kra_meet_code == meet,
        Race.race_date_local == race_date,
    ).scalar_subquery()
    total = session.scalar(
        select(func.count()).select_from(RaceEntry).where(RaceEntry.race_id.in_(race_ids))
    )
    missing = session.scalar(
        select(func.count()).select_from(RaceEntry).where(
            RaceEntry.race_id.in_(race_ids),
            RaceEntry.gate_number.is_(None),
        )
    )
    return bool(total and not missing)


def _write_gate_numbers(
    session: Session,
    *,
    meet: int,
    items: list[GateEntrySheetItem],
    observed_at_ms: int,
) -> int:
    if not items:
        return 0

    racecourse = session.scalar(select(Racecourse).where(Racecourse.kra_meet_code == meet))
    if racecourse is None:
        raise ValueError(f"출발번호를 연결할 경마장이 없습니다: meet={meet}")

    dates = {item.race_date for item in items}
    races = list(
        session.scalars(
            select(Race).where(
                Race.racecourse_id == racecourse.id,
                Race.race_date_local.in_(dates),
            )
        )
    )
    races_by_key = {(race.race_date_local, race.race_number): race for race in races}
    entries_by_race: dict[int, list[RaceEntry]] = {}
    if races:
        for entry in session.scalars(
            select(RaceEntry)
            .options(
                joinedload(RaceEntry.horse),
                selectinload(RaceEntry.equipment_changes),
            )
            .where(RaceEntry.race_id.in_([race.id for race in races]))
        ):
            entries_by_race.setdefault(entry.race_id, []).append(entry)
    written = 0
    for item in items:
        race = races_by_key.get((item.race_date, item.race_number))
        if race is None:
            raise ValueError(
                "출발번호와 연결할 경주가 없습니다: "
                f"meet={meet}, date={item.race_date}, race={item.race_number}"
            )

        entries = entries_by_race.get(race.id, [])

        by_number = {entry.horse_number: entry for entry in entries}
        entry = by_number.get(item.gate_number)
        expected_name = _name_key(item.horse_name)
        if entry is None:
            name_matches = [
                candidate
                for candidate in entries
                if _name_key(candidate.horse.name_ko) == expected_name
            ]
            if len(name_matches) == 1:
                candidate = name_matches[0]
                raise ValueError(
                    "API78 출발번호와 기존 출주번호가 다릅니다: "
                    f"date={item.race_date}, race={item.race_number}, horse={item.horse_name}, "
                    f"gate={item.gate_number}, horse_number={candidate.horse_number}"
                )
            raise ValueError(
                "출발번호와 연결할 출전마가 없습니다: "
                f"date={item.race_date}, race={item.race_number}, "
                f"gate={item.gate_number}, horse={item.horse_name}"
            )

        if _name_key(entry.horse.name_ko) != expected_name:
            raise ValueError(
                "API78 출발번호의 마명이 기존 출전표와 다릅니다: "
                f"date={item.race_date}, race={item.race_number}, gate={item.gate_number}, "
                f"api={item.horse_name}, stored={entry.horse.name_ko}"
            )
        if entry.gate_number is not None and entry.gate_number != item.gate_number:
            raise ValueError(
                "이미 저장된 출발번호와 API78 값이 다릅니다: "
                f"entry={entry.id}, stored={entry.gate_number}, api={item.gate_number}"
            )

        entry.gate_number = item.gate_number
        if item.equipment_card_raw is not None and (
            entry.equipment_card_observed_at_ms is None
            or observed_at_ms >= entry.equipment_card_observed_at_ms
        ):
            entry.equipment_card_raw = item.equipment_card_raw
            entry.equipment_card_observed_at_ms = observed_at_ms
            marks = {
                position: (name, change_type)
                for position, name, change_type in parse_equipment_changes(
                    item.equipment_card_raw
                )
            }
            existing = {mark.position: mark for mark in entry.equipment_changes}
            for position, mark in existing.items():
                if position not in marks:
                    entry.equipment_changes.remove(mark)
            for position, (name, change_type) in marks.items():
                mark = existing.get(position)
                if mark is None:
                    entry.equipment_changes.append(
                        EntryEquipmentChange(
                            position=position,
                            equipment_name_raw=name,
                            change_type=change_type,
                            observed_at_ms=observed_at_ms,
                        )
                    )
                else:
                    mark.equipment_name_raw = name
                    mark.change_type = change_type
                    mark.observed_at_ms = observed_at_ms
        written += 1

    session.flush()
    return written


def _name_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip()
    # Historical API78 cards prefix some otherwise identical horse names with
    # a decorative star (for example ★은빛나래 in the 2017-01-07 Seoul card).
    normalized = normalized.removeprefix("★").strip()
    # KRA sources use different home-region labels for the same runner
    # (for example ``[부]`` versus ``[영남]``).  Gate and entry number are
    # already matched above, so compare the stable base horse name here.
    normalized = re.sub(r"^\[[^\]]+\]\s*", "", normalized)
    normalized = normalized.removeprefix("★").strip()
    return "".join(normalized.split()).casefold()


def _now_ms() -> int:
    return time.time_ns() // 1_000_000
