from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from datetime import time as datetime_time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from horse_racing.collectors.kra_api import (
    AI_RACE_RESULT_ENDPOINT,
    AI_RACE_RESULT_OPERATION,
    DETAILED_RACE_RESULT_ENDPOINT,
    DETAILED_RACE_RESULT_OPERATION,
    FINAL_DIVIDEND_ENDPOINT,
    FINAL_DIVIDEND_OPERATION,
    RACE_PLAN_ENDPOINT,
    RACE_PLAN_OPERATION,
    KraApiClient,
    response_body,
)
from horse_racing.db.models import (
    Horse,
    IngestionRun,
    Jockey,
    OddsSnapshot,
    Owner,
    Race,
    Racecourse,
    RaceEntry,
    RaceResult,
    SourceDocument,
    Trainer,
)
from horse_racing.parsers.race_day import (
    AiRaceResultItem,
    DetailedRaceResultItem,
    FinalDividendItem,
    RacePlanItem,
    parse_body_weight,
    parse_items,
    parse_track_status,
)
from horse_racing.services.entry_sheet import (
    IngestionSummary,
    _upsert_person,
    _upsert_racecourse,
    ingest_entry_sheet,
)
from horse_racing.services.raw_store import store_kra_page

Writer = Callable[[Session, int, list[Any]], int]


@dataclass(frozen=True, slots=True)
class DatasetDefinition:
    data_type: str
    source: str
    endpoint: str
    operation: str
    public_params: dict[str, str | int]


@dataclass(frozen=True, slots=True)
class RaceDayIngestionSummary:
    stages: dict[str, IngestionSummary]

    @property
    def records_fetched(self) -> int:
        return sum(stage.records_fetched for stage in self.stages.values())

    @property
    def records_written(self) -> int:
        return sum(stage.records_written for stage in self.stages.values())


@dataclass(frozen=True, slots=True)
class EntryPeopleRepairSummary:
    examined: int
    repaired: int
    unresolved: int


def repair_missing_entry_people(session: Session) -> EntryPeopleRepairSummary:
    missing_entries = list(
        session.scalars(
            select(RaceEntry).where(
                (RaceEntry.trainer_id.is_(None)) | (RaceEntry.owner_id.is_(None))
            )
        )
    )
    repaired = 0
    for entry in missing_entries:
        if entry.trainer_id is None:
            trainer_ids = list(
                session.scalars(
                    select(RaceEntry.trainer_id)
                    .where(
                        RaceEntry.horse_id == entry.horse_id,
                        RaceEntry.trainer_id.is_not(None),
                    )
                    .distinct()
                )
            )
            if len(trainer_ids) == 1:
                entry.trainer_id = trainer_ids[0]
        if entry.owner_id is None:
            owner_ids = list(
                session.scalars(
                    select(RaceEntry.owner_id)
                    .where(
                        RaceEntry.horse_id == entry.horse_id,
                        RaceEntry.owner_id.is_not(None),
                    )
                    .distinct()
                )
            )
            if len(owner_ids) == 1:
                entry.owner_id = owner_ids[0]
        if entry.trainer_id is not None and entry.owner_id is not None:
            repaired += 1
    session.commit()
    return EntryPeopleRepairSummary(
        examined=len(missing_entries),
        repaired=repaired,
        unresolved=len(missing_entries) - repaired,
    )


def result_data_exists(
    client: KraApiClient,
    *,
    race_date: str,
    meet: int,
) -> bool:
    fetched = next(
        client.iter_pages(
            endpoint=AI_RACE_RESULT_ENDPOINT,
            operation=AI_RACE_RESULT_OPERATION,
            public_params={"rccrs_cd": meet, "race_dt": race_date, "_type": "json"},
            page_size=1,
        )
    )
    body = response_body(fetched.payload)
    try:
        return int(body.get("totalCount") or 0) > 0
    except (TypeError, ValueError):
        return False


def race_day_is_complete(
    session: Session,
    *,
    race_date: date,
    meet: int,
) -> bool:
    all_race_count = session.scalar(
        select(func.count())
        .select_from(Race)
        .join(Race.racecourse)
        .where(
            Racecourse.kra_meet_code == meet,
            Race.race_date_local == race_date,
        )
    )
    race_ids = list(
        session.scalars(
            select(Race.id)
            .join(Race.racecourse)
            .where(
                Racecourse.kra_meet_code == meet,
                Race.race_date_local == race_date,
                Race.status == "completed",
            )
        )
    )
    if not race_ids or all_race_count != len(race_ids):
        return False
    entry_count = session.scalar(
        select(func.count()).select_from(RaceEntry).where(RaceEntry.race_id.in_(race_ids))
    )
    result_count = session.scalar(
        select(func.count())
        .select_from(RaceResult)
        .join(RaceEntry)
        .where(RaceEntry.race_id.in_(race_ids))
    )
    odds_count = session.scalar(
        select(func.count()).select_from(OddsSnapshot).where(OddsSnapshot.race_id.in_(race_ids))
    )
    completed_dividend_run = final_dividend_is_complete(
        session,
        race_date=race_date,
        meet=meet,
    )
    return bool(entry_count and result_count and odds_count and completed_dividend_run)


def result_day_is_stored(
    session: Session,
    *,
    race_date: date,
    meet: int,
) -> bool:
    race_count = session.scalar(
        select(func.count())
        .select_from(Race)
        .join(Race.racecourse)
        .where(
            Racecourse.kra_meet_code == meet,
            Race.race_date_local == race_date,
            Race.status == "completed",
        )
    )
    return bool(race_count)


def final_dividend_is_complete(
    session: Session,
    *,
    race_date: date,
    meet: int,
) -> bool:
    completed_dividend_run = session.scalar(
        select(func.count())
        .select_from(IngestionRun)
        .join(SourceDocument)
        .where(
            IngestionRun.data_type == "final_dividend",
            IngestionRun.status == "completed",
            func.json_extract(SourceDocument.request_params_json, "$.meet") == meet,
            func.json_extract(SourceDocument.request_params_json, "$.rc_date")
            == race_date.strftime("%Y%m%d"),
        )
    )
    return bool(completed_dividend_run)


def ingest_race_schedule(
    session: Session,
    client: KraApiClient,
    *,
    race_date: str,
    meet: int,
    raw_data_dir: Path,
    page_size: int = 1000,
) -> RaceDayIngestionSummary:
    common = {"rccrs_cd": meet, "race_dt": race_date, "_type": "json"}
    stages: dict[str, IngestionSummary] = {}
    stages["race_plan"] = _ingest_dataset(
        session,
        client,
        definition=DatasetDefinition(
            data_type="race_plan",
            source="data.go.kr/B551015/API154",
            endpoint=RACE_PLAN_ENDPOINT,
            operation=RACE_PLAN_OPERATION,
            public_params=common,
        ),
        item_model=RacePlanItem,
        writer=_write_race_plans,
        race_date=race_date,
        meet=meet,
        raw_data_dir=raw_data_dir,
        page_size=page_size,
    )
    stages["entry_sheet"] = ingest_entry_sheet(
        session,
        client,
        race_date=race_date,
        meet=meet,
        raw_data_dir=raw_data_dir,
        page_size=page_size,
    )
    return RaceDayIngestionSummary(stages=stages)


def ingest_race_day(
    session: Session,
    client: KraApiClient,
    *,
    race_date: str,
    meet: int,
    raw_data_dir: Path,
    page_size: int = 1000,
    include_dividends: bool = True,
) -> RaceDayIngestionSummary:
    """Collect the five foundational datasets for one racecourse and race date."""
    common = {"rccrs_cd": meet, "race_dt": race_date, "_type": "json"}
    schedule_summary = ingest_race_schedule(
        session,
        client,
        race_date=race_date,
        meet=meet,
        raw_data_dir=raw_data_dir,
        page_size=page_size,
    )
    stages = dict(schedule_summary.stages)
    stages["ai_race_result"] = _ingest_dataset(
        session,
        client,
        definition=DatasetDefinition(
            data_type="ai_race_result",
            source="data.go.kr/B551015/API155",
            endpoint=AI_RACE_RESULT_ENDPOINT,
            operation=AI_RACE_RESULT_OPERATION,
            public_params=common,
        ),
        item_model=AiRaceResultItem,
        writer=_write_ai_results,
        race_date=race_date,
        meet=meet,
        raw_data_dir=raw_data_dir,
        page_size=page_size,
    )
    stages["detailed_race_result"] = _ingest_dataset(
        session,
        client,
        definition=DatasetDefinition(
            data_type="detailed_race_result",
            source="data.go.kr/B551015/API156",
            endpoint=DETAILED_RACE_RESULT_ENDPOINT,
            operation=DETAILED_RACE_RESULT_OPERATION,
            public_params=common,
        ),
        item_model=DetailedRaceResultItem,
        writer=_write_detailed_results,
        race_date=race_date,
        meet=meet,
        raw_data_dir=raw_data_dir,
        page_size=page_size,
    )
    if include_dividends:
        stages["final_dividend"] = ingest_final_dividends(
            session,
            client,
            race_date=race_date,
            meet=meet,
            raw_data_dir=raw_data_dir,
            page_size=page_size,
        )
    return RaceDayIngestionSummary(stages=stages)


def ingest_final_dividends(
    session: Session,
    client: KraApiClient,
    *,
    race_date: str,
    meet: int,
    raw_data_dir: Path,
    page_size: int = 20_000,
) -> IngestionSummary:
    return _ingest_dataset(
        session,
        client,
        definition=DatasetDefinition(
            data_type="final_dividend",
            source="data.go.kr/B551015/API301",
            endpoint=FINAL_DIVIDEND_ENDPOINT,
            operation=FINAL_DIVIDEND_OPERATION,
            public_params={"meet": meet, "rc_date": race_date, "_type": "json"},
        ),
        item_model=FinalDividendItem,
        writer=_write_final_dividends,
        race_date=race_date,
        meet=meet,
        raw_data_dir=raw_data_dir,
        page_size=page_size,
    )


def _ingest_dataset[ItemT: BaseModel](
    session: Session,
    client: KraApiClient,
    *,
    definition: DatasetDefinition,
    item_model: type[ItemT],
    writer: Writer,
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


def _write_race_plans(session: Session, meet: int, items: list[RacePlanItem]) -> int:
    racecourse = _upsert_racecourse(session, meet)
    for item in items:
        race = _upsert_race(session, racecourse, item.race_date, item.race_number, item.distance_m)
        race.race_day_count = item.race_day_count
        race.field_size = item.field_size
        race.grade = item.grade or race.grade
        race.race_name = item.race_name or race.race_name
        race.burden_type = item.burden_type
        race.age_condition = item.age_condition
        race.sex_condition = item.sex_condition
        race.rating_condition = item.rating_condition
        race.newcomer_condition = item.newcomer_condition
        race.scheduled_at_ms = _local_datetime_ms(item.race_date, item.scheduled_time)
        race.weather = item.weather
        race.track_condition, race.track_moisture_percent = parse_track_status(item.track_status)
        if race.status != "completed":
            race.status = "scheduled"
    return len(items)


def _write_ai_results(session: Session, meet: int, items: list[AiRaceResultItem]) -> int:
    racecourse = _upsert_racecourse(session, meet)
    observed_at_ms = _now_ms()
    for item in items:
        race = _upsert_race(session, racecourse, item.race_date, item.race_number, item.distance_m)
        race.race_name = item.race_name or race.race_name
        race.status = "completed"
        horse = _upsert_horse(
            session,
            kra_horse_id=item.horse_id,
            name_ko=item.horse_name,
            name_en=item.horse_name_en,
            birth_date=item.birth_date,
            sex=item.sex,
            origin_country=item.origin_country,
        )
        entry = _upsert_entry(session, race, horse, item.horse_number)
        _set_entry_measurements(
            entry,
            carried_weight_kg=item.carried_weight_kg,
            rating=item.rating,
            body_weight_text=item.body_weight_text,
        )
        _upsert_result(
            session,
            entry,
            finish_position=item.finish_position,
            finish_time_ms=item.finish_time_ms,
            margin_text=item.margin_text,
        )
        _write_individual_odds(
            session,
            race,
            item.horse_number,
            item.win_odds,
            item.place_odds,
            observed_at_ms,
        )
    return len(items)


def _write_detailed_results(
    session: Session,
    meet: int,
    items: list[DetailedRaceResultItem],
) -> int:
    racecourse = _upsert_racecourse(session, meet)
    observed_at_ms = _now_ms()
    for item in items:
        race = _upsert_race(session, racecourse, item.race_date, item.race_number, item.distance_m)
        race.race_day_count = item.race_day_count
        race.race_name = item.race_name or race.race_name
        race.grade = item.grade or race.grade
        race.burden_type = item.burden_type
        race.age_condition = item.age_condition
        race.sex_condition = item.sex_condition
        race.rating_condition = item.rating_condition
        race.scheduled_at_ms = _local_datetime_ms(item.race_date, item.scheduled_time)
        race.actual_start_at_ms = _local_datetime_ms(item.race_date, item.actual_start_time)
        race.start_time_change_reason = item.start_time_change_reason
        race.weather = item.weather
        race.track_condition, race.track_moisture_percent = parse_track_status(item.track_status)
        race.status = "completed"

        horse = _upsert_horse(
            session,
            kra_horse_id=item.horse_id,
            name_ko=item.horse_name,
            birth_date=item.birth_date,
            sex=item.sex,
            origin_country=item.origin_country,
        )
        entry = _upsert_entry(session, race, horse, item.horse_number)
        _set_entry_measurements(
            entry,
            carried_weight_kg=item.carried_weight_kg,
            rating=item.rating,
            body_weight_text=item.body_weight_text,
        )
        entry.equipment = item.equipment
        jockey = _upsert_person(
            session, Jockey, "kra_jockey_id", item.jockey_id, item.jockey_name, None
        )
        trainer = _upsert_person(
            session, Trainer, "kra_trainer_id", item.trainer_id, item.trainer_name, None
        )
        owner = _upsert_person(session, Owner, "kra_owner_id", item.owner_id, item.owner_name, None)
        if jockey is not None:
            entry.jockey = jockey
        if trainer is not None:
            entry.trainer = trainer
        if owner is not None:
            entry.owner = owner
        _upsert_result(
            session,
            entry,
            finish_position=item.finish_position,
            finish_time_ms=item.finish_time_ms,
            margin_text=item.margin_text,
            prize_money_krw=item.prize_money_krw,
            bonus_prize_money_krw=item.bonus_prize_money_krw,
            rank_remark=item.rank_remark,
        )
        _write_individual_odds(
            session,
            race,
            item.horse_number,
            item.win_odds,
            item.place_odds,
            observed_at_ms,
        )
    return len(items)


def _write_final_dividends(
    session: Session,
    meet: int,
    items: list[FinalDividendItem],
) -> int:
    racecourse = _upsert_racecourse(session, meet)
    observed_at_ms = _now_ms()
    records_written = 0
    for item in items:
        if item.odds is None:
            continue
        race = _find_race(session, racecourse, item.race_date, item.race_number)
        if race is None:
            raise ValueError(
                f"배당과 연결할 경주가 없습니다: meet={meet}, "
                f"date={item.race_date}, race={item.race_number}"
            )
        _upsert_final_odds(
            session,
            race,
            bet_type=item.bet_type,
            selection_key=item.selection_key,
            odds=item.odds,
            observed_at_ms=observed_at_ms,
        )
        records_written += 1
    return records_written


def _upsert_race(
    session: Session,
    racecourse: Racecourse,
    race_date: date,
    race_number: int,
    distance_m: int,
) -> Race:
    race = _find_race(session, racecourse, race_date, race_number)
    if race is None:
        race = Race(
            racecourse=racecourse,
            race_date_local=race_date,
            race_number=race_number,
            distance_m=distance_m,
        )
        session.add(race)
    race.distance_m = distance_m
    session.flush()
    return race


def _find_race(
    session: Session,
    racecourse: Racecourse,
    race_date: date,
    race_number: int,
) -> Race | None:
    return session.scalar(
        select(Race).where(
            Race.racecourse_id == racecourse.id,
            Race.race_date_local == race_date,
            Race.race_number == race_number,
        )
    )


def _upsert_horse(
    session: Session,
    *,
    kra_horse_id: str,
    name_ko: str,
    name_en: str | None = None,
    birth_date: date | None = None,
    sex: str | None = None,
    origin_country: str | None = None,
) -> Horse:
    horse = session.scalar(select(Horse).where(Horse.kra_horse_id == kra_horse_id))
    if horse is None:
        horse = Horse(kra_horse_id=kra_horse_id, name_ko=name_ko)
        session.add(horse)
    horse.name_ko = name_ko
    horse.name_en = name_en or horse.name_en
    horse.birth_date = birth_date or horse.birth_date
    horse.sex = sex or horse.sex
    horse.origin_country = origin_country or horse.origin_country
    session.flush()
    return horse


def _upsert_entry(
    session: Session,
    race: Race,
    horse: Horse,
    horse_number: int,
) -> RaceEntry:
    entry = session.scalar(
        select(RaceEntry).where(RaceEntry.race_id == race.id, RaceEntry.horse_id == horse.id)
    )
    if entry is None:
        entry = session.scalar(
            select(RaceEntry).where(
                RaceEntry.race_id == race.id,
                RaceEntry.horse_number == horse_number,
            )
        )
    if entry is None:
        entry = RaceEntry(race=race, horse=horse, horse_number=horse_number)
        session.add(entry)
    else:
        entry.horse = horse
        entry.horse_number = horse_number
    entry.scratched = False
    session.flush()
    return entry


def _set_entry_measurements(
    entry: RaceEntry,
    *,
    carried_weight_kg: float | None,
    rating: float | None,
    body_weight_text: str | None,
) -> None:
    entry.carried_weight_kg = carried_weight_kg
    entry.rating = rating
    body_weight, body_weight_change = parse_body_weight(body_weight_text)
    entry.body_weight_kg = body_weight
    entry.body_weight_change_kg = body_weight_change


def _upsert_result(
    session: Session,
    entry: RaceEntry,
    *,
    finish_position: int | None,
    finish_time_ms: int | None,
    margin_text: str | None,
    prize_money_krw: int | None = None,
    bonus_prize_money_krw: int | None = None,
    rank_remark: str | None = None,
) -> RaceResult:
    result = session.scalar(select(RaceResult).where(RaceResult.race_entry_id == entry.id))
    if result is None:
        result = RaceResult(race_entry=entry)
        session.add(result)
    result.finish_position = finish_position
    result.finish_time_ms = finish_time_ms
    result.margin_text = margin_text
    result.prize_money_krw = prize_money_krw or result.prize_money_krw
    result.bonus_prize_money_krw = bonus_prize_money_krw or result.bonus_prize_money_krw
    result.rank_remark = rank_remark or result.rank_remark
    return result


def _write_individual_odds(
    session: Session,
    race: Race,
    horse_number: int,
    win_odds: float | None,
    place_odds: float | None,
    observed_at_ms: int,
) -> None:
    for bet_type, odds in (("WIN", win_odds), ("PLC", place_odds)):
        if odds is not None and odds > 0:
            _upsert_final_odds(
                session,
                race,
                bet_type=bet_type,
                selection_key=str(horse_number),
                odds=odds,
                observed_at_ms=observed_at_ms,
            )


def _upsert_final_odds(
    session: Session,
    race: Race,
    *,
    bet_type: str,
    selection_key: str,
    odds: float,
    observed_at_ms: int,
) -> OddsSnapshot:
    snapshot = session.scalar(
        select(OddsSnapshot).where(
            OddsSnapshot.race_id == race.id,
            OddsSnapshot.bet_type == bet_type,
            OddsSnapshot.selection_key == selection_key,
        )
    )
    if snapshot is None:
        snapshot = OddsSnapshot(
            race=race,
            bet_type=bet_type,
            selection_key=selection_key,
            odds=odds,
            observed_at_ms=observed_at_ms,
        )
        session.add(snapshot)
    else:
        snapshot.odds = odds
        snapshot.observed_at_ms = observed_at_ms
    return snapshot


def _local_datetime_ms(race_date: date, time_text: str | None) -> int | None:
    if not time_text:
        return None
    digits = "".join(character for character in time_text if character.isdigit())
    if len(digits) not in {3, 4, 5, 6}:
        return None
    digits = digits.zfill(6 if len(digits) > 4 else 4)
    try:
        if len(digits) == 4:
            local_time = datetime_time(hour=int(digits[:2]), minute=int(digits[2:]))
        else:
            local_time = datetime_time(
                hour=int(digits[:2]),
                minute=int(digits[2:4]),
                second=int(digits[4:]),
            )
    except ValueError:
        return None
    local_datetime = datetime.combine(race_date, local_time, tzinfo=ZoneInfo("Asia/Seoul"))
    return int(local_datetime.timestamp() * 1000)


def _now_ms() -> int:
    return time.time_ns() // 1_000_000
