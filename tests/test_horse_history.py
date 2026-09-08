from datetime import date
from pathlib import Path

import httpx
from sqlalchemy import func, select
from test_race_day import api_payload, migrated_session

from horse_racing.collectors.kra_api import (
    DAILY_TRAINING_ENDPOINT,
    ENTRY_HORSE_WEIGHT_ENDPOINT,
    RACE_HORSE_CLINIC_ENDPOINT,
    RACE_HORSE_INFO_ENDPOINT,
    RACE_HORSE_RATING_ENDPOINT,
    KraApiClient,
)
from horse_racing.db.models import (
    Horse,
    HorseMedical,
    HorseProfileSnapshot,
    HorseRatingSnapshot,
    HorseTraining,
    HorseWeightHistory,
)
from horse_racing.parsers.horse_history import (
    HorseDetailItem,
    HorseMedicalItem,
    HorseRatingItem,
    HorseTrainingItem,
    HorseWeightItem,
    parse_meet_code,
)
from horse_racing.services.horse_history import (
    ingest_horse_profiles,
    ingest_medical,
    ingest_ratings,
    ingest_training,
    ingest_weights,
)


def rating_payload() -> dict[str, object]:
    return api_payload(
        [
            {
                "hrName": "빅토리",
                "hrNo": "0022348",
                "meet": "서울",
                "rating1": 81,
                "rating2": 82,
                "rating3": 82,
                "rating4": 102,
            }
        ]
    )


def weight_payload() -> dict[str, object]:
    return api_payload(
        [
            {
                "chulNo": 1,
                "hrName": "고스트윈드",
                "hrNo": "0056309",
                "meet": "서울",
                "rcDate": 20260822,
                "rcNo": 1,
                "wgHr": 493,
                "wgHrDiff": 1,
            }
        ]
    )


def training_payload() -> dict[str, object]:
    return api_payload(
        [
            {
                "chulGubun": "금주출전예정",
                "hrName": "마이티원더",
                "hrNo": "0062606",
                "meet": "서울",
                "part": 2,
                "partNo": 22,
                "prGubun": "기수",
                "prNo": "080417",
                "run1Cnt": 1,
                "run2Cnt": 0,
                "spTime": 20260820065300,
                "stTime": 20260820063600,
                "trDate": 20260820,
                "trName": "문세영",
                "trTerm": 1020,
            }
        ]
    )


def medical_payload() -> dict[str, object]:
    return api_payload(
        [
            {
                "clinicDate": 20260820,
                "hospiName": "명성동물병원",
                "hrName": "강나루",
                "hrNo": "0051286",
                "illName1": "양후지 근육통",
                "illName2": "-",
                "meet": "서울",
                "part": 28,
            }
        ]
    )


def profile_payload() -> dict[str, object]:
    return api_payload(
        [
            {
                "birthday": 20240324,
                "chaksunT": 3750000,
                "faHrName": "CARACARO",
                "faHrNo": 6149511,
                "hrLastAmt": "56,979천원(개별)",
                "hrName": "가라카이",
                "hrNo": "0058062",
                "meet": "서울",
                "moHrName": "ALGOWILD",
                "moHrNo": 6128634,
                "name": "미국",
                "ord1CntT": 0,
                "ord1CntY": 0,
                "ord2CntT": 0,
                "ord2CntY": 0,
                "ord3CntT": 0,
                "ord3CntY": 0,
                "owName": "에스지이건설",
                "owNo": 121013,
                "rank": "외4",
                "rating": 0,
                "rcCntT": 1,
                "rcCntY": 1,
                "sex": "수",
                "trName": "정호익",
                "trNo": "070148",
            }
        ]
    )


def test_parse_meet_code() -> None:
    assert parse_meet_code("서울") == 1
    assert parse_meet_code("부산경남") == 3
    assert parse_meet_code("영남") == 3
    assert parse_meet_code("부경") == 3
    assert parse_meet_code(2) == 2


def test_parse_history_items() -> None:
    rating = HorseRatingItem.model_validate(
        {
            "hrName": "빅토리",
            "hrNo": "0022348",
            "meet": "서울",
            "rating1": 81,
            "rating4": 102,
        }
    )
    assert rating.meet_code == 1
    assert rating.rating_4 == 102.0

    weight = HorseWeightItem.model_validate(
        {
            "hrNo": "0056309",
            "hrName": "고스트윈드",
            "meet": "서울",
            "rcDate": 20260822,
            "rcNo": 1,
            "chulNo": 1,
            "wgHr": 493,
            "wgHrDiff": -2,
        }
    )
    assert weight.race_date == date(2026, 8, 22)
    assert weight.body_weight_change_kg == -2

    training = HorseTrainingItem.model_validate(
        {
            "chulGubun": "금주출전예정",
            "hrName": "마이티원더",
            "hrNo": "0062606",
            "meet": "서울",
            "run1Cnt": 1,
            "run2Cnt": 0,
            "spTime": 20260820065300,
            "stTime": 20260820063600,
            "trDate": 20260820,
            "trName": "문세영",
            "trTerm": 1020,
        }
    )
    assert training.duration_seconds == 1020
    assert training.started_at_raw == "20260820063600"

    medical = HorseMedicalItem.model_validate(
        {
            "clinicDate": 20260820,
            "hospiName": "명성동물병원",
            "hrName": "강나루",
            "hrNo": "0051286",
            "illName1": "양후지 근육통",
            "illName2": "-",
            "meet": "서울",
            "part": 28,
        }
    )
    assert medical.diagnosis_2 is None
    assert medical.clinic_date == date(2026, 8, 20)

    detail = HorseDetailItem.model_validate(
        profile_payload()["response"]["body"]["items"]["item"][0]
    )
    assert detail.birth_date == date(2024, 3, 24)
    assert detail.sire_name == "CARACARO"
    assert detail.grade == "외4"
    assert detail.prize_money_total_krw == 3_750_000


def test_ingest_horse_history_tables(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith(RACE_HORSE_RATING_ENDPOINT):
            return httpx.Response(200, json=rating_payload())
        if path.endswith(ENTRY_HORSE_WEIGHT_ENDPOINT):
            return httpx.Response(200, json=weight_payload())
        if path.endswith(DAILY_TRAINING_ENDPOINT):
            return httpx.Response(200, json=training_payload())
        if path.endswith(RACE_HORSE_CLINIC_ENDPOINT):
            return httpx.Response(200, json=medical_payload())
        if path.endswith(RACE_HORSE_INFO_ENDPOINT):
            return httpx.Response(200, json=profile_payload())
        return httpx.Response(404, json={"message": path})

    transport = httpx.MockTransport(handler)
    session_factory = migrated_session(tmp_path)
    with session_factory() as session:
        with KraApiClient("test-key", transport=transport) as client:
            rating_summary = ingest_ratings(
                session,
                client,
                snapshot_date="20260825",
                raw_data_dir=tmp_path / "raw",
            )
            weight_summary = ingest_weights(
                session,
                client,
                race_date="20260822",
                meet=1,
                raw_data_dir=tmp_path / "raw",
            )
            training_summary = ingest_training(
                session,
                client,
                training_date="20260820",
                meet=1,
                raw_data_dir=tmp_path / "raw",
            )
            medical_summary = ingest_medical(
                session,
                client,
                clinic_date="20260820",
                meet=1,
                raw_data_dir=tmp_path / "raw",
            )
            profile_summary = ingest_horse_profiles(
                session,
                client,
                meet=1,
                snapshot_date="20260825",
                raw_data_dir=tmp_path / "raw",
            )

        assert rating_summary.records_written == 1
        assert weight_summary.records_written == 1
        assert training_summary.records_written == 1
        assert medical_summary.records_written == 1
        assert profile_summary.records_written == 1
        assert session.scalar(select(func.count()).select_from(Horse)) == 5
        assert session.scalar(select(func.count()).select_from(HorseRatingSnapshot)) == 1
        assert session.scalar(select(func.count()).select_from(HorseWeightHistory)) == 1
        assert session.scalar(select(func.count()).select_from(HorseTraining)) == 1
        assert session.scalar(select(func.count()).select_from(HorseMedical)) == 1
        assert session.scalar(select(func.count()).select_from(HorseProfileSnapshot)) == 1

        weight = session.scalar(select(HorseWeightHistory))
        assert weight is not None
        assert weight.body_weight_kg == 493
        assert weight.body_weight_change_kg == 1

        horse = session.scalar(select(Horse).where(Horse.kra_horse_id == "0058062"))
        assert horse is not None
        assert horse.grade == "외4"
        assert horse.sire_name == "CARACARO"
        assert horse.dam_name == "ALGOWILD"
        assert horse.birth_date == date(2024, 3, 24)
