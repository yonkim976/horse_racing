import json
from datetime import date, timedelta
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
    HorseMedicalDiagnosis,
    HorseProfileSnapshot,
    HorseRatingSnapshot,
    HorseTraining,
    HorseWeightHistory,
    MedicalDiagnosisTerm,
    SourceDocument,
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
    _write_medical,
    _write_ratings,
    _write_training,
    ingest_horse_active_statuses,
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

        assert rating_summary.records_fetched == 1
        assert rating_summary.records_written == 0
        assert weight_summary.records_written == 1
        assert training_summary.records_written == 1
        assert medical_summary.records_written == 1
        assert profile_summary.records_written == 1
        assert session.scalar(select(func.count()).select_from(Horse)) == 4
        assert session.scalar(select(func.count()).select_from(HorseRatingSnapshot)) == 0
        assert session.scalar(select(func.count()).select_from(HorseWeightHistory)) == 1
        assert session.scalar(select(func.count()).select_from(HorseTraining)) == 1
        assert session.scalar(select(func.count()).select_from(HorseMedical)) == 1
        assert session.scalar(select(func.count()).select_from(MedicalDiagnosisTerm)) == 1
        assert session.scalar(select(func.count()).select_from(HorseMedicalDiagnosis)) == 1
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
        assert horse.is_active is True
        assert horse.active_status_observed_at_ms is not None
        assert horse.active_status_source == "data.go.kr/B551015/API8_2:act_gubun=y"

        with KraApiClient("test-key", transport=transport) as client:
            inactive_summary = ingest_horse_profiles(
                session,
                client,
                meet=1,
                snapshot_date="20260825",
                raw_data_dir=tmp_path / "raw",
                include_inactive=True,
            )
        assert inactive_summary.records_written == 1
        session.refresh(horse)
        assert horse.is_active is True
        assert horse.active_status_source == "data.go.kr/B551015/API8_2:act_gubun=y"


def test_api77_archive_preserves_existing_snapshots_and_both_region_raw_rows(tmp_path: Path):
    first = rating_payload()["response"]["body"]["items"]["item"][0]
    second = {**first, "meet": "영남", "rating1": 109, "rating4": None}
    payload = api_payload([first, second])
    factory = migrated_session(tmp_path)
    with factory() as session:
        horse = Horse(kra_horse_id=first["hrNo"], name_ko="원래 이름")
        snapshot = HorseRatingSnapshot(
            horse=horse, meet_code=1, rating_1=81, rating_4=102, observed_at_ms=1
        )
        session.add(snapshot)
        session.commit()
        with KraApiClient(
            "test-key",
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)),
        ) as client:
            summary = ingest_ratings(
                session, client, snapshot_date="20261001", raw_data_dir=tmp_path / "raw"
            )
        assert summary.records_fetched == 2
        assert summary.records_written == 0
        session.refresh(snapshot)
        assert (snapshot.meet_code, snapshot.rating_1, snapshot.rating_4) == (1, 81, 102)
        assert horse.name_ko == "원래 이름"
        assert session.scalar(select(func.count()).select_from(HorseRatingSnapshot)) == 1
        document = session.scalar(select(SourceDocument))
        assert document is not None
        raw = json.loads(Path(document.local_path).read_text())
        assert raw["response"]["body"]["items"]["item"] == [first, second]


def test_batched_history_keeps_identity_duplicates_and_snapshots(tmp_path: Path) -> None:
    factory = migrated_session(tmp_path)
    rating = HorseRatingItem.model_validate(
        rating_payload()["response"]["body"]["items"]["item"][0]
    )
    training = HorseTrainingItem.model_validate(
        training_payload()["response"]["body"]["items"]["item"][0]
    )
    with factory() as session:
        session.add(Horse(kra_horse_id=rating.horse_id, name_ko="기존이름", sex="수", meet_code=1))
        session.commit()
        assert _write_ratings(session, [rating, rating], 12345) == 2
        session.commit()
        assert _write_ratings(session, [rating.model_copy(update={"rating_1": 90.0})], 12345) == 1
        assert _write_ratings(session, [rating], 12346) == 1
        assert _write_training(session, [training, training], 12345) == 2
        session.commit()
        assert (
            _write_training(
                session, [training.model_copy(update={"duration_seconds": 1200})], 12346
            )
            == 1
        )
        assert _write_ratings(session, [], 12347) == 0
        assert _write_training(session, [], 12347) == 0
        session.commit()
        assert session.scalar(select(func.count()).select_from(Horse)) == 2
        assert session.scalar(select(func.count()).select_from(HorseRatingSnapshot)) == 2
        assert session.scalar(select(func.count()).select_from(HorseTraining)) == 1
        horse = session.scalar(select(Horse).where(Horse.kra_horse_id == rating.horse_id))
        assert horse.name_ko == rating.horse_name
        assert horse.sex == "수" and horse.meet_code == 1
        snapshot = session.scalar(
            select(HorseRatingSnapshot).where(HorseRatingSnapshot.observed_at_ms == 12345)
        )
        assert snapshot.rating_1 == 90.0
        row = session.scalar(select(HorseTraining))
        assert row.duration_seconds == 1200 and row.observed_at_ms == 12346


def test_training_overlapping_week_replay_keeps_ids_and_multiple_sessions(tmp_path: Path):
    """Seven-day daily windows must not append the same session repeatedly."""
    template = training_payload()["response"]["body"]["items"]["item"][0]
    factory = migrated_session(tmp_path)
    seen_ids = {}
    start = date(2026, 9, 26)
    with factory() as session:
        for offset in range(3):
            end = start + timedelta(days=6 + offset)
            for ago in range(6, -1, -1):
                day = end - timedelta(days=ago)
                label = day.strftime("%Y%m%d")
                items = [
                    HorseTrainingItem.model_validate(
                        {**template, "trDate": label, "stTime": begin, "spTime": finish}
                    )
                    for begin, finish in (
                        (label + "063600", label + "065300"),
                        (label + "070000", label + "071000"),
                        (None, None),
                    )
                ]
                _write_training(session, items + items, 100 + offset)
                session.commit()
                rows = session.scalars(
                    select(HorseTraining).where(HorseTraining.training_date_local == day)
                ).all()
                assert len(rows) == 3
                ids = {row.id for row in rows}
                if day in seen_ids:
                    assert ids == seen_ids[day]
                seen_ids[day] = ids
        assert session.scalar(select(func.count()).select_from(HorseTraining)) == 9 * 3
        # An empty response means no new observation, not removal of old rows.
        assert _write_training(session, [], 999) == 0
        session.commit()
        assert session.scalar(select(func.count()).select_from(HorseTraining)) == 9 * 3


def test_training_pg_lock_is_ordered_before_existing_row_lookup():
    from unittest.mock import Mock, patch

    template = training_payload()["response"]["body"]["items"]["item"][0]
    items = [
        HorseTrainingItem.model_validate({**template, "meet": meet, "trDate": day})
        for meet, day in ((3, "20260927"), (1, "20260926"), (3, "20260927"))
    ]
    session = Mock()
    session.get_bind.return_value.dialect.name = "postgresql"

    def lookup(_session, _items):
        assert [call.args[1]["scope"] for call in session.execute.call_args_list] == [
            120260926,
            320260927,
        ]
        raise RuntimeError("lookup reached after locks")

    import pytest

    with patch("horse_racing.services.horse_history._history_horses", side_effect=lookup):
        with pytest.raises(RuntimeError, match="lookup reached"):
            _write_training(session, items, 123)
    assert all(
        str(call.args[0]) == "SELECT pg_advisory_xact_lock(:namespace, :scope)"
        and call.args[1]["namespace"] == 181001
        for call in session.execute.call_args_list
    )


def test_active_status_union_wins_over_inactive_at_another_meet(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith(RACE_HORSE_INFO_ENDPOINT)
        return httpx.Response(200, json=profile_payload())

    session_factory = migrated_session(tmp_path)
    with session_factory() as session:
        with KraApiClient("test-key", transport=httpx.MockTransport(handler)) as client:
            summary = ingest_horse_active_statuses(
                session,
                client,
                meets=[1, 2],
                snapshot_date="20260825",
                raw_data_dir=tmp_path / "raw",
            )

        horse = session.scalar(select(Horse).where(Horse.kra_horse_id == "0058062"))
        assert horse is not None
        assert horse.is_active is True
        assert horse.active_status_source == "data.go.kr/B551015/API8_2:act_gubun=y"
        assert summary.records_fetched == 4
        assert summary.records_written == 1


def test_medical_terms_deduplicate_without_changing_source_text(tmp_path: Path) -> None:
    session_factory = migrated_session(tmp_path)
    items = [
        HorseMedicalItem.model_validate(
            {
                "hrNo": horse_no,
                "hrName": horse_name,
                "meet": "서울",
                "clinicDate": 20260925,
                "hospiName": "검증병원",
                "illName1": "양후지 근육통",
                "illName2": second,
            }
        )
        for horse_no, horse_name, second in (
            ("0000001", "검증마일", "각막염"),
            ("0000002", "검증마이", "-"),
        )
    ]
    with session_factory() as session:
        assert _write_medical(session, items, 12345) == 2
        session.commit()
        assert _write_medical(session, items, 12346) == 2
        session.commit()

        assert session.scalar(select(func.count()).select_from(HorseMedical)) == 2
        assert session.scalar(select(func.count()).select_from(MedicalDiagnosisTerm)) == 2
        assert session.scalar(select(func.count()).select_from(HorseMedicalDiagnosis)) == 3
        assert set(session.scalars(select(MedicalDiagnosisTerm.raw_text))) == {
            "양후지 근육통",
            "각막염",
        }
        first = session.scalar(select(HorseMedical).where(HorseMedical.diagnosis_2 == "각막염"))
        assert first is not None
        assert first.diagnosis_1 == "양후지 근육통"
