import json
from datetime import date
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select
from test_race_day import (
    ENTRY_FIXTURE,
    ai_result_payload,
    api_payload,
    detailed_result_payload,
    final_dividend_payload,
    migrated_session,
    race_plan_payload,
)

from horse_racing.collectors.kra_api import RACE_RESULT_WITH_SECTIONS_ENDPOINT, KraApiClient
from horse_racing.db.models import RaceSectionResult
from horse_racing.parsers.race_section import (
    RaceResultSectionItem,
    parse_section_values,
    section_specs_for_meet,
)
from horse_racing.services.race_day import ingest_race_day
from horse_racing.services.race_sections import ingest_race_sections, section_day_is_stored


def section_result_payload() -> dict[str, object]:
    return api_payload(
        [
            {
                "rcDate": "20260822",
                "rcNo": 1,
                "rcDist": 1200,
                "chulNo": 1,
                "hrNo": "5001",
                "hrName": "테스트원",
                "meet": "서울",
                "seS1fAccTime": 12.3,
                "sjS1fOrd": 2,
                "se_3cAccTime": 35.1,
                "sj_3cOrd": 1,
                "seG1fAccTime": 75.2,
                "sjG1fOrd": 1,
            },
            {
                "rcDate": "20260822",
                "rcNo": 1,
                "rcDist": 1200,
                "chulNo": 2,
                "hrNo": "005002",
                "hrName": "테스트투",
                "meet": "서울",
                "seS1fAccTime": 12.1,
                "sjS1fOrd": 1,
                "se_3cAccTime": 35.4,
                "sj_3cOrd": 2,
                "seG1fAccTime": 76.0,
                "sjG1fOrd": 2,
            },
        ]
    )


def test_section_specs_by_meet() -> None:
    assert [spec.code for spec in section_specs_for_meet(1)][:2] == ["S1F", "1C"]
    assert [spec.code for spec in section_specs_for_meet(3)][:2] == ["S1F", "G8F"]
    assert [spec.code for spec in section_specs_for_meet(2)][:3] == ["S1F", "1C", "2C"]


def test_jeju_corner_fields_are_preserved():
    item = RaceResultSectionItem.model_validate(
        {
            "rcDate": "20260815",
            "rcNo": 7,
            "rcDist": 1610,
            "chulNo": 4,
            "hrNo": "test",
            "hrName": "테스트",
            "je_1cTime": 19.9,
            "je_2cTime": 35.5,
            "sj_1cOrd": 8,
            "sj_2cOrd": 8,
        }
    )
    values = {s.section_code: s for s in parse_section_values(item, 2)}
    assert values["1C"].elapsed_time_ms == 19900
    assert values["2C"].elapsed_time_ms == 35500
    assert values["2C"].position == 8


def test_parse_section_values_for_seoul_sample() -> None:
    item = RaceResultSectionItem.model_validate(
        {
            "rcDate": "20260822",
            "rcNo": 1,
            "rcDist": 1000,
            "chulNo": 4,
            "hrNo": "0055757",
            "hrName": "하이라이트",
            "meet": "서울",
            "seS1fAccTime": 13.5,
            "sjS1fOrd": 1,
            "se_3cAccTime": 13.5,
            "sj_3cOrd": 1,
            "seG1fAccTime": 47.4,
            "sjG1fOrd": 1,
        }
    )

    sections = parse_section_values(item, meet=1)
    by_code = {section.section_code: section for section in sections}

    assert item.race_date == date(2026, 8, 22)
    assert by_code["S1F"].elapsed_time_ms == 13_500
    assert by_code["S1F"].position == 1
    assert by_code["G1F"].elapsed_time_ms == 47_400


def test_parse_section_values_skips_empty_sections() -> None:
    item = RaceResultSectionItem.model_validate(
        {
            "rcDate": "20260822",
            "rcNo": 1,
            "rcDist": 1000,
            "chulNo": 1,
            "hrNo": "0050001",
            "hrName": "테스트",
            "meet": "서울",
        }
    )

    assert parse_section_values(item, meet=1) == []


def test_section_specs_reject_unknown_meet() -> None:
    with pytest.raises(ValueError):
        section_specs_for_meet(9)


def test_section_day_is_stored_ignores_special_finish_codes(tmp_path: Path) -> None:
    from horse_racing.db.models import (
        Horse,
        Race,
        Racecourse,
        RaceEntry,
        RaceResult,
        RaceSectionResult,
    )

    session_factory = migrated_session(tmp_path)
    with session_factory() as session:
        racecourse = Racecourse(kra_meet_code=1, code="seoul", name_ko="서울")
        session.add(racecourse)
        race = Race(
            racecourse=racecourse,
            race_date_local=date(2026, 1, 2),
            race_number=1,
            distance_m=1200,
            status="completed",
        )
        session.add(race)

        for hn, hid, name, pos, has_s1f in (
            (1, "0050001", "정상마", 1, True),
            (2, "0050002", "제외마", 94, False),
            (3, "0050003", "취소마", 99, False),
        ):
            horse = Horse(kra_horse_id=hid, name_ko=name)
            entry = RaceEntry(race=race, horse=horse, horse_number=hn)
            session.add_all([horse, entry, RaceResult(race_entry=entry, finish_position=pos)])
            if has_s1f:
                session.add(
                    RaceSectionResult(
                        race_entry=entry,
                        section_code="S1F",
                        elapsed_time_ms=13_000,
                        position=1,
                    )
                )
        session.commit()

        assert section_day_is_stored(session, race_date=date(2026, 1, 2), meet=1)


def test_section_day_is_stored_true_when_all_races_cancelled(tmp_path: Path) -> None:
    from horse_racing.db.models import Horse, Race, Racecourse, RaceEntry, RaceResult

    session_factory = migrated_session(tmp_path)
    with session_factory() as session:
        racecourse = Racecourse(kra_meet_code=2, code="jeju", name_ko="제주")
        race = Race(
            racecourse=racecourse,
            race_date_local=date(2026, 3, 20),
            race_number=1,
            distance_m=1000,
            status="completed",
        )
        horse = Horse(kra_horse_id="3100001", name_ko="취소마")
        entry = RaceEntry(race=race, horse=horse, horse_number=1)
        session.add_all(
            [racecourse, race, horse, entry, RaceResult(race_entry=entry, finish_position=99)]
        )
        session.commit()

        assert section_day_is_stored(session, race_date=date(2026, 3, 20), meet=2)


def test_ingest_race_sections_links_entries_and_is_idempotent(tmp_path: Path) -> None:
    entry_payload = ENTRY_FIXTURE.read_text(encoding="utf-8")
    responses = {
        "/B551015/API154/racePlan": race_plan_payload(),
        "/B551015/API26_2/entrySheet_2": json.loads(entry_payload),
        "/B551015/API155/raceResult": ai_result_payload(),
        "/B551015/API156/raceRsutDtl": detailed_result_payload(),
        "/B551015/API301/Dividend_rate_total": final_dividend_payload(),
        f"/B551015{RACE_RESULT_WITH_SECTIONS_ENDPOINT}": section_result_payload(),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path not in responses:
            raise AssertionError(f"unexpected path: {path}")
        return httpx.Response(200, json=responses[path], request=request)

    session_factory = migrated_session(tmp_path)
    with (
        KraApiClient("secret-test-key", transport=httpx.MockTransport(handler)) as client,
        session_factory() as session,
    ):
        ingest_race_day(
            session,
            client,
            race_date="20260822",
            meet=1,
            raw_data_dir=tmp_path / "raw",
        )
        first = ingest_race_sections(
            session,
            client,
            race_date="20260822",
            meet=1,
            raw_data_dir=tmp_path / "raw",
        )
        second = ingest_race_sections(
            session,
            client,
            race_date="20260822",
            meet=1,
            raw_data_dir=tmp_path / "raw",
        )

        assert first.records_fetched == 2
        assert first.records_written == 6
        assert second.records_written == 6
        assert session.scalar(select(func.count()).select_from(RaceSectionResult)) == 6
        assert section_day_is_stored(session, race_date=date(2026, 8, 22), meet=1)

        s1f = session.scalar(
            select(RaceSectionResult).where(RaceSectionResult.section_code == "S1F")
        )
        assert s1f is not None
        assert s1f.elapsed_time_ms == 12_300
        assert s1f.position == 2
