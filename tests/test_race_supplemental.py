from datetime import date
from pathlib import Path

import httpx
from sqlalchemy import func, select
from test_race_day import api_payload, migrated_session

from horse_racing.collectors.kra_api import (
    HORSE_EQUIPMENT_ENDPOINT,
    HORSE_GRADE_CHANGE_ENDPOINT,
    JUDGE_REPORT_ENDPOINT,
    RACE_HORSE_CANCEL_ENDPOINT,
    START_TRAINING_ENDPOINT,
    KraApiClient,
)
from horse_racing.db.models import (
    EntryEquipment,
    HorseGradeChange,
    HorseStartTraining,
    JockeyChange,
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
from horse_racing.services.race_supplemental import (
    ingest_equipment,
    ingest_grade_changes,
    ingest_jockey_changes,
    ingest_scratches,
    ingest_start_training,
    ingest_steward_reports,
)


def jockey_change_payload() -> dict[str, object]:
    return api_payload(
        [
            {
                "aftBudam": 52.5,
                "befBudam": 52.5,
                "chulNo": 1,
                "hrName": "골드퀸즈",
                "hrNo": "0051322",
                "jkAft": "080515",
                "jkAftName": "조한별",
                "jkBef": "080487",
                "jkBefName": "임기원",
                "meet": "서울",
                "rcDate": 20260726,
                "rcNo": 6,
                "reason": "복통",
            }
        ]
    )


def scratch_payload() -> dict[str, object]:
    return api_payload(
        [
            {
                "chulNo": 8,
                "hrName": "은빛돌풍",
                "hrNo": "0046387",
                "meet": "서울",
                "rcDate": 20260822,
                "rcNo": 8,
                "reason": "마체이상",
            }
        ]
    )


def equipment_payload() -> dict[str, object]:
    return api_payload(
        [
            {
                "bleedingCnt": 0,
                "bleedingDate": "-",
                "chulNo": 1,
                "hrName": "고스트윈드",
                "hrNo": "0056309",
                "illName": "2026.08.06양각막염",
                "meet": "서울",
                "rcDate": 20260822,
                "rcNo": 1,
                "toolName": "눈가리개",
            }
        ]
    )


def grade_payload() -> dict[str, object]:
    return api_payload(
        [
            {
                "beforeRank": "국4",
                "blood": "더러브렛",
                "hrName": "글로벌서브",
                "hrNo": "0051855",
                "meet": "서울",
                "rank": "국3",
                "spDate": "-",
                "stDate": 20260824,
            }
        ]
    )


def start_training_payload() -> dict[str, object]:
    return api_payload(
        [
            {
                "hrName": "대기원",
                "hrNo": 3104784,
                "meet": "제주",
                "part": 1,
                "partNo": 21,
                "prName": "김길홍",
                "remark": "양호",
                "trDate": 20260823,
            }
        ]
    )


def steward_payload() -> dict[str, object]:
    return api_payload(
        [
            {
                "addJudgement": "-",
                "jkChange": "-",
                "judgement": "출전제외 조치",
                "meet": "서울",
                "member": "김일경(수석)",
                "rcDate": 20260822,
                "rcNo": 1,
                "weather": "흐리고 비",
            }
        ]
    )


def test_parse_jockey_change_item() -> None:
    item = JockeyChangeItem.model_validate(
        jockey_change_payload()["response"]["body"]["items"]["item"][0]
    )
    assert item.horse_id == "0051322"
    assert item.jockey_before_name == "임기원"
    assert item.jockey_after_name == "조한별"
    assert item.race_date == date(2026, 7, 26)


def test_parse_grade_change_optional_end() -> None:
    item = HorseGradeChangeItem.model_validate(
        grade_payload()["response"]["body"]["items"]["item"][0]
    )
    assert item.start_date == date(2026, 8, 24)
    assert item.end_date is None
    assert item.grade_before == "국4"
    assert item.grade_after == "국3"


def test_parse_start_training_numeric_horse_id() -> None:
    item = StartTrainingItem.model_validate(
        start_training_payload()["response"]["body"]["items"]["item"][0]
    )
    assert item.horse_id == "3104784"
    assert item.meet_code == 2
    assert item.rider_name == "김길홍"


def test_ingest_jockey_changes(tmp_path: Path) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json=jockey_change_payload())
    )
    session_factory = migrated_session(tmp_path)
    with (
        KraApiClient("test-key", transport=transport) as client,
        session_factory() as session,
    ):
        summary = ingest_jockey_changes(
            session,
            client,
            race_date="20260726",
            meet=1,
            raw_data_dir=tmp_path / "raw",
        )
        assert summary.records_written == 1
        assert session.scalar(select(func.count()).select_from(JockeyChange)) == 1
        row = session.scalar(select(JockeyChange))
        assert row is not None
        assert row.jockey_after_name == "조한별"
        assert row.reason == "복통"


def test_ingest_scratches_and_equipment(tmp_path: Path) -> None:
    responses = {
        RACE_HORSE_CANCEL_ENDPOINT: scratch_payload(),
        HORSE_EQUIPMENT_ENDPOINT: equipment_payload(),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        for endpoint, payload in responses.items():
            if endpoint in str(request.url):
                return httpx.Response(200, json=payload)
        return httpx.Response(404)

    session_factory = migrated_session(tmp_path)
    with (
        KraApiClient("test-key", transport=httpx.MockTransport(handler)) as client,
        session_factory() as session,
    ):
        scratch_summary = ingest_scratches(
            session, client, race_date="20260822", meet=1, raw_data_dir=tmp_path / "raw"
        )
        equip_summary = ingest_equipment(
            session, client, race_date="20260822", meet=1, raw_data_dir=tmp_path / "raw"
        )
        assert scratch_summary.records_written == 1
        assert equip_summary.records_written == 1
        assert session.scalar(select(func.count()).select_from(RaceScratch)) == 1
        assert session.scalar(select(func.count()).select_from(EntryEquipment)) == 1
        equip = session.scalar(select(EntryEquipment))
        assert equip is not None
        assert equip.equipment_raw == "눈가리개"
        assert equip.illness_note == "2026.08.06양각막염"


def test_ingest_grade_start_steward(tmp_path: Path) -> None:
    responses = {
        HORSE_GRADE_CHANGE_ENDPOINT: grade_payload(),
        START_TRAINING_ENDPOINT: start_training_payload(),
        JUDGE_REPORT_ENDPOINT: steward_payload(),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        for endpoint, payload in responses.items():
            if endpoint in str(request.url):
                return httpx.Response(200, json=payload)
        return httpx.Response(404)

    session_factory = migrated_session(tmp_path)
    with (
        KraApiClient("test-key", transport=httpx.MockTransport(handler)) as client,
        session_factory() as session,
    ):
        grade = ingest_grade_changes(
            session,
            client,
            snapshot_date="20260825",
            meet=1,
            raw_data_dir=tmp_path / "raw",
        )
        start = ingest_start_training(
            session,
            client,
            training_date="20260823",
            meet=2,
            raw_data_dir=tmp_path / "raw",
        )
        steward = ingest_steward_reports(
            session,
            client,
            race_date="20260822",
            meet=1,
            raw_data_dir=tmp_path / "raw",
        )
        assert grade.records_written == 1
        assert start.records_written == 1
        assert steward.records_written == 1
        assert session.scalar(select(func.count()).select_from(HorseGradeChange)) == 1
        assert session.scalar(select(func.count()).select_from(HorseStartTraining)) == 1
        assert session.scalar(select(func.count()).select_from(RaceStewardReport)) == 1
        report = session.scalar(select(RaceStewardReport))
        assert report is not None
        assert report.weather == "흐리고 비"
        assert "출전제외" in (report.judgement or "")


def test_parse_scratch_and_steward_items() -> None:
    scratch = RaceScratchItem.model_validate(
        scratch_payload()["response"]["body"]["items"]["item"][0]
    )
    steward = StewardReportItem.model_validate(
        steward_payload()["response"]["body"]["items"]["item"][0]
    )
    equip = EntryEquipmentItem.model_validate(
        equipment_payload()["response"]["body"]["items"]["item"][0]
    )
    nameless = EntryEquipmentItem.model_validate(
        {
            "bleedingCnt": 0,
            "bleedingDate": "-",
            "chulNo": 14,
            "hrName": None,
            "hrNo": "0051457",
            "meet": "서울",
            "rcDate": 20260215,
            "rcNo": 7,
            "toolName": "계란형큰고리재갈,눈가면,망사눈가면",
        }
    )
    assert scratch.reason == "마체이상"
    assert steward.additional_judgement is None
    assert equip.bleeding_date_raw is None
    assert nameless.horse_name == "(이름없음)"
    assert nameless.horse_id == "0051457"
