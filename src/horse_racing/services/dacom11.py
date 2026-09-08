from __future__ import annotations

import hashlib
import json
import re
import time
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

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
    RaceSectionResult,
    SourceDocument,
    Trainer,
)
from horse_racing.parsers.dacom11 import Dacom11Entry, Dacom11Race, parse_dacom11_report
from horse_racing.services.entry_sheet import MEET_METADATA


@dataclass(frozen=True, slots=True)
class Dacom11IngestionSummary:
    run_id: int
    files: int
    races_parsed: int
    entries_parsed: int
    races_written: int
    entries_written: int
    overlap_races: int
    overlap_entries: int
    overlap_mismatches: int
    races_updated: int
    resolved_horse_entries: int
    unresolved_horse_entries: int
    ambiguous_horse_entries: int
    synthetic_horses: int


def ingest_dacom11_reports(
    session: Session,
    *,
    raw_data_dir: Path,
    start_date: date,
    end_date: date,
    meets: list[int],
    validate_only: bool = False,
    allow_synthetic_horses: bool = False,
) -> Dacom11IngestionSummary:
    if end_date < start_date:
        raise ValueError("종료일이 시작일보다 앞설 수 없습니다.")
    documents = _source_documents(
        session,
        start_date=start_date,
        end_date=end_date,
        meets=meets,
        raw_data_dir=raw_data_dir,
    )
    run = IngestionRun(
        source="race.kra.co.kr/dbdata/dacom11",
        data_type="kra_text_dacom11_ingest",
        started_at_ms=_now_ms(),
        status="running",
    )
    session.add(run)
    session.commit()

    counters = {
        "files": 0,
        "races_parsed": 0,
        "entries_parsed": 0,
        "races_written": 0,
        "entries_written": 0,
        "overlap_races": 0,
        "overlap_entries": 0,
        "overlap_mismatches": 0,
        "races_updated": 0,
        "resolved_horse_entries": 0,
        "unresolved_horse_entries": 0,
        "ambiguous_horse_entries": 0,
        "synthetic_horses": 0,
    }
    resolver = _EntityResolver(session)
    try:
        for document, meet in documents:
            file_path = Path(document.local_path)
            raw = file_path.read_bytes()
            parsed_races = [
                race
                for race in parse_dacom11_report(raw)
                if start_date <= race.race_date <= end_date
            ]
            _copy_source_document(session, run.id, document)
            counters["files"] += 1
            counters["races_parsed"] += len(parsed_races)
            counters["entries_parsed"] += sum(len(race.entries) for race in parsed_races)
            for parsed in parsed_races:
                stored = _stored_race(session, parsed.race_date, parsed.race_number, meet)
                if stored is not None:
                    compared, mismatches = _compare_overlap(session, stored, parsed)
                    counters["overlap_races"] += 1
                    counters["overlap_entries"] += compared
                    counters["overlap_mismatches"] += mismatches
                    if not validate_only and _fill_missing_race_metadata(stored, parsed):
                        counters["races_updated"] += 1
                    continue
                if validate_only:
                    for item in parsed.entries:
                        _horse, resolution = resolver.match_horse(
                            item,
                            meet=meet,
                            race_date=parsed.race_date,
                        )
                        counters[f"{resolution}_horse_entries"] += 1
                    continue
                race, entries_written, synthetic = _write_race(
                    session,
                    parsed,
                    meet=meet,
                    observed_at_ms=document.retrieved_at_ms,
                    resolver=resolver,
                    allow_synthetic_horses=allow_synthetic_horses,
                )
                counters["races_written"] += 1
                counters["entries_written"] += entries_written
                counters["synthetic_horses"] += synthetic
                if race.id is None:
                    raise RuntimeError("dacom11 경주 ID가 생성되지 않았습니다.")
            run.records_fetched = counters["entries_parsed"]
            run.records_written = counters["entries_written"]
            session.commit()

        run.status = "completed"
        run.completed_at_ms = _now_ms()
        session.commit()
    except Exception as exc:
        session.rollback()
        failed_run = session.get(IngestionRun, run.id)
        if failed_run is not None:
            failed_run.status = "failed"
            failed_run.completed_at_ms = _now_ms()
            failed_run.records_fetched = counters["entries_parsed"]
            failed_run.records_written = counters["entries_written"]
            failed_run.error_message = str(exc)[:2000]
            session.commit()
        raise

    return Dacom11IngestionSummary(run_id=run.id, **counters)


def _source_documents(
    session: Session,
    *,
    start_date: date,
    end_date: date,
    meets: list[int],
    raw_data_dir: Path,
) -> list[tuple[SourceDocument, int]]:
    documents = list(
        session.scalars(
            select(SourceDocument)
            .where(SourceDocument.operation == "dacom11")
            .order_by(SourceDocument.retrieved_at_ms.desc(), SourceDocument.id.desc())
        )
    )
    selected: dict[str, tuple[SourceDocument, int]] = {}
    for document in documents:
        path = Path(document.local_path)
        if not path.is_file():
            continue
        params = json.loads(document.request_params_json)
        meet = int(params.get("meet", 0))
        if meet not in meets:
            continue
        filename_date = _leading_date(path.name)
        if filename_date is not None and not start_date <= filename_date <= end_date:
            continue
        selected.setdefault(str(path.resolve()), (document, meet))

    if selected:
        return sorted(selected.values(), key=lambda item: (item[1], item[0].local_path))

    # Manifest만 남고 SourceDocument가 없는 복구 상황을 위한 로컬 fallback.
    for meet in meets:
        root = raw_data_dir / "kra_text" / "dacom11" / f"meet={meet}"
        for path in root.glob("**/*dacom11.rpt"):
            file_date = _leading_date(path.name)
            if file_date is None or not start_date <= file_date <= end_date:
                continue
            raise ValueError(f"SourceDocument 없이 남은 dacom11 파일입니다: {path}")
    return []


def _write_race(
    session: Session,
    parsed: Dacom11Race,
    *,
    meet: int,
    observed_at_ms: int,
    resolver: _EntityResolver,
    allow_synthetic_horses: bool,
) -> tuple[Race, int, int]:
    racecourse = session.scalar(select(Racecourse).where(Racecourse.kra_meet_code == meet))
    if racecourse is None:
        code, name = MEET_METADATA[meet]
        racecourse = Racecourse(kra_meet_code=meet, code=code, name_ko=name)
        session.add(racecourse)
        session.flush()
    race = Race(
        racecourse=racecourse,
        race_date_local=parsed.race_date,
        race_number=parsed.race_number,
        distance_m=parsed.distance_m,
        grade=parsed.grade,
        race_name=parsed.race_name,
        race_day_count=parsed.race_day_count,
        field_size=len(parsed.entries),
        burden_type=parsed.burden_type,
        age_condition=parsed.age_condition,
        rating_condition=parsed.rating_condition,
        weather=parsed.weather,
        track_condition=parsed.track_condition,
        track_moisture_percent=parsed.track_moisture_percent,
        status="completed",
    )
    session.add(race)
    session.flush()

    synthetic_count = 0
    for item in parsed.entries:
        horse, synthetic = resolver.horse(
            item,
            meet=meet,
            race_date=parsed.race_date,
            allow_synthetic=allow_synthetic_horses,
        )
        synthetic_count += int(synthetic)
        entry = RaceEntry(
            race=race,
            horse=horse,
            jockey=resolver.person(Jockey, item.jockey_name, meet=meet),
            trainer=resolver.person(Trainer, item.trainer_name, meet=meet),
            owner=resolver.person(Owner, item.owner_name, meet=meet),
            horse_number=item.horse_number,
            gate_number=item.horse_number,
            carried_weight_kg=item.carried_weight_kg,
            body_weight_kg=item.body_weight_kg,
            body_weight_change_kg=item.body_weight_change_kg,
            rating=item.rating,
            scratched=(item.finish_position is not None and item.finish_position >= 90),
        )
        session.add(entry)
        session.flush()
        session.add(
            RaceResult(
                race_entry=entry,
                finish_position=item.finish_position,
                finish_time_ms=item.finish_time_ms,
                margin_text=item.margin_text,
                prize_money_krw=item.prize_money_krw,
                rank_remark=(item.finish_rank_raw if not item.finish_rank_raw.isdigit() else None),
                disqualified=item.finish_rank_raw == "실격",
            )
        )
        _write_sections(session, entry, item)
        _write_odds(session, race, item, observed_at_ms)
    return race, len(parsed.entries), synthetic_count


def _compare_overlap(session: Session, race: Race, parsed: Dacom11Race) -> tuple[int, int]:
    entries = list(
        session.scalars(
            select(RaceEntry)
            .options(joinedload(RaceEntry.horse), joinedload(RaceEntry.result))
            .where(RaceEntry.race_id == race.id)
        )
    )
    by_number = {entry.horse_number: entry for entry in entries}
    mismatches = 0
    for item in parsed.entries:
        stored = by_number.get(item.horse_number)
        if stored is None:
            mismatches += 1
            continue
        if not _horse_names_match(stored.horse.name_ko, item.horse_name):
            mismatches += 1
        if stored.result is None or stored.result.finish_position != item.finish_position:
            mismatches += 1
        if item.finish_time_ms is not None and (
            stored.result is None or stored.result.finish_time_ms != item.finish_time_ms
        ):
            mismatches += 1
    for number in set(by_number) - {item.horse_number for item in parsed.entries}:
        stored = by_number[number]
        is_expected_omission = stored.scratched or (
            stored.result is not None
            and stored.result.finish_position is not None
            and stored.result.finish_position >= 90
        )
        if not is_expected_omission:
            mismatches += 1
    return len(parsed.entries), mismatches


def _fill_missing_race_metadata(race: Race, parsed: Dacom11Race) -> bool:
    changed = False
    values = {
        "distance_m": parsed.distance_m,
        "grade": parsed.grade,
        "race_name": parsed.race_name,
        "race_day_count": parsed.race_day_count,
        "field_size": len(parsed.entries),
        "burden_type": parsed.burden_type,
        "age_condition": parsed.age_condition,
        "rating_condition": parsed.rating_condition,
        "weather": parsed.weather,
        "track_condition": parsed.track_condition,
        "track_moisture_percent": parsed.track_moisture_percent,
    }
    for attribute, value in values.items():
        if getattr(race, attribute) is None and value is not None:
            setattr(race, attribute, value)
            changed = True
    return changed


class _EntityResolver:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.horses_by_name = _group_by_name(list(session.scalars(select(Horse))))
        self.people: dict[type[Jockey] | type[Trainer] | type[Owner], dict[str, list[object]]] = {
            Jockey: _group_by_name(list(session.scalars(select(Jockey)))),
            Trainer: _group_by_name(list(session.scalars(select(Trainer)))),
            Owner: _group_by_name(list(session.scalars(select(Owner)))),
        }

    def horse(
        self,
        item: Dacom11Entry,
        *,
        meet: int,
        race_date: date,
        allow_synthetic: bool,
    ) -> tuple[Horse, bool]:
        horse, resolution = self.match_horse(item, meet=meet, race_date=race_date)
        if horse is not None:
            return horse, False
        if not allow_synthetic:
            raise ValueError(
                "공식 마번으로 연결되지 않은 과거 경주마입니다: "
                f"date={race_date}, meet={meet}, horse={item.horse_name}, "
                f"resolution={resolution}"
            )
        birth_year = race_date.year - item.age if item.age is not None else None
        token = _identity_token(meet, item.horse_name, birth_year, item.sex)
        kra_id = f"text:{token}"
        horse = self.session.scalar(select(Horse).where(Horse.kra_horse_id == kra_id))
        if horse is None:
            horse = Horse(
                kra_horse_id=kra_id,
                name_ko=item.horse_name,
                sex=item.sex,
                origin_country=item.origin_country,
                meet_code=meet,
            )
            self.session.add(horse)
            self.session.flush()
            self.horses_by_name.setdefault(_horse_name_key(item.horse_name), []).append(horse)
        return horse, True

    def match_horse(
        self,
        item: Dacom11Entry,
        *,
        meet: int,
        race_date: date,
    ) -> tuple[Horse | None, str]:
        horse_name_key = _horse_name_key(item.horse_name)
        candidates = list(self.horses_by_name.get(horse_name_key, []))
        if not candidates and len(horse_name_key) >= 6:
            candidates = [
                horse
                for stored_name, horses in self.horses_by_name.items()
                if stored_name.startswith(horse_name_key)
                for horse in horses
            ]
        birth_year = race_date.year - item.age if item.age is not None else None
        birth_matches = [
            horse
            for horse in candidates
            if birth_year is not None
            and horse.birth_date is not None
            and horse.birth_date.year == birth_year
        ]
        if len(birth_matches) == 1:
            return birth_matches[0], "resolved"
        if len(birth_matches) > 1:
            candidates = birth_matches
        home_meet = _horse_home_meet(item.horse_name) or meet
        meet_candidates = [
            horse
            for horse in candidates
            if horse.meet_code is None or horse.meet_code == home_meet
        ]
        if meet_candidates:
            candidates = meet_candidates
        sex_matches = [
            horse
            for horse in candidates
            if item.sex is not None and horse.sex == item.sex
        ]
        if len(sex_matches) == 1:
            return sex_matches[0], "resolved"
        if len(candidates) == 1:
            return candidates[0], "resolved"
        return None, "ambiguous" if candidates else "unresolved"

    def person[T: Jockey | Trainer | Owner](
        self,
        model: type[T],
        name: str | None,
        *,
        meet: int,
    ) -> T | None:
        if not name:
            return None
        candidates = self.people[model].get(_name_key(name), [])
        if len(candidates) == 1:
            return candidates[0]  # type: ignore[return-value]
        prefix = {Jockey: "jockey", Trainer: "trainer", Owner: "owner"}[model]
        scoped_meet = meet if model is Trainer else 0
        kra_id = f"text:{prefix}:{_identity_token(scoped_meet, name, None, None)}"
        id_field = {Jockey: "kra_jockey_id", Trainer: "kra_trainer_id", Owner: "kra_owner_id"}[
            model
        ]
        person = self.session.scalar(select(model).where(getattr(model, id_field) == kra_id))
        if person is None:
            person = model(**{id_field: kra_id, "name_ko": name})
            self.session.add(person)
            self.session.flush()
            self.people[model].setdefault(_name_key(name), []).append(person)
        return person


def _write_sections(session: Session, entry: RaceEntry, item: Dacom11Entry) -> None:
    passing = (item.passing_order_raw or "").split("-")
    positions = {}
    if len(passing) == 6:
        for code, value in zip(("S1F", "1C", "2C", "3C", "4C", "G1F"), passing, strict=True):
            if value.strip().isdigit() and 0 < int(value.strip()) < 90:
                positions[code] = int(value.strip())
    for code, elapsed in (("S1F", item.s1f_ms), ("G3F", item.g3f_ms), ("G1F", item.g1f_ms),
                          *item.corner_times_ms.items()):
        if elapsed is not None:
            session.add(
                RaceSectionResult(
                    race_entry=entry,
                    section_code=code,
                    elapsed_time_ms=elapsed,
                    position=positions.get(code),
                    group_notation_raw=item.passing_order_raw,
                )
            )


def _write_odds(
    session: Session,
    race: Race,
    item: Dacom11Entry,
    observed_at_ms: int,
) -> None:
    for bet_type, odds in (("WIN", item.win_odds), ("PLC", item.place_odds)):
        if odds is not None and odds > 0:
            session.add(
                OddsSnapshot(
                    race=race,
                    bet_type=bet_type,
                    selection_key=str(item.horse_number),
                    odds=odds,
                    observed_at_ms=observed_at_ms,
                )
            )


def _stored_race(session: Session, race_date: date, race_number: int, meet: int) -> Race | None:
    return session.scalar(
        select(Race)
        .join(Racecourse)
        .where(
            Racecourse.kra_meet_code == meet,
            Race.race_date_local == race_date,
            Race.race_number == race_number,
        )
    )


def _copy_source_document(session: Session, run_id: int, source: SourceDocument) -> None:
    session.add(
        SourceDocument(
            ingestion_run_id=run_id,
            source_url=source.source_url,
            endpoint=source.endpoint,
            operation="dacom11_parse",
            request_params_json=source.request_params_json,
            requested_at_ms=source.requested_at_ms,
            retrieved_at_ms=source.retrieved_at_ms,
            http_status_code=source.http_status_code,
            content_type=source.content_type,
            response_bytes=source.response_bytes,
            local_path=source.local_path,
            sha256=source.sha256,
        )
    )


def _group_by_name(entities: list[object]) -> dict[str, list[object]]:
    grouped: dict[str, list[object]] = {}
    for entity in entities:
        grouped.setdefault(_name_key(entity.name_ko), []).append(entity)  # type: ignore[attr-defined]
    return grouped


def _name_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return "".join(normalized.split()).casefold()


def _horse_name_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip()
    normalized = re.sub(r"^\[(?:서|부|제)\]\s*", "", normalized)
    return _name_key(normalized)


def _horse_home_meet(value: str) -> int | None:
    matched = re.match(r"^\[(서|제|부)\]", unicodedata.normalize("NFKC", value).strip())
    return {"서": 1, "제": 2, "부": 3}.get(matched.group(1)) if matched else None


def _horse_names_match(stored_name: str, report_name: str) -> bool:
    stored_key = _horse_name_key(stored_name)
    report_key = _horse_name_key(report_name)
    return stored_key == report_key or (
        len(report_key) >= 6 and stored_key.startswith(report_key)
    )


def _identity_token(meet: int, name: str, birth_year: int | None, sex: str | None) -> str:
    raw = f"{meet}|{_name_key(name)}|{birth_year or ''}|{sex or ''}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def _leading_date(filename: str) -> date | None:
    if len(filename) < 8 or not filename[:8].isdigit():
        return None
    try:
        return date.fromisoformat(f"{filename[:4]}-{filename[4:6]}-{filename[6:8]}")
    except ValueError:
        return None


def _now_ms() -> int:
    return time.time_ns() // 1_000_000
