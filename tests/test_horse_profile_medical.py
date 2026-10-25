import httpx
import pytest
from sqlalchemy import func, select
from test_horse_history import medical_payload, profile_payload
from test_race_day import migrated_session

from horse_racing.collectors.kra_api import (
    RACE_HORSE_CLINIC_ENDPOINT,
    RACE_HORSE_INFO_ENDPOINT,
    KraApiClient,
)
from horse_racing.db.models import HorseMedical, HorseMedicalDiagnosis, HorseProfileSnapshot
from horse_racing.jobs.horse_profile_medical import ScopeCheckedApi
from horse_racing.parsers.horse_history import HorseDetailItem, HorseMedicalItem
from horse_racing.services.horse_history import _write_medical, _write_profiles


@pytest.mark.parametrize("wrong", ["date", "meet"])
def test_checked_clinic_rejects_wrong_scope(wrong):
    payload = medical_payload()
    row = payload["response"]["body"]["items"]["item"][0]
    row["clinicDate" if wrong == "date" else "meet"] = 20260821 if wrong == "date" else "제주"
    with KraApiClient(
        "test", transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    ) as client:
        with pytest.raises(ValueError, match="mismatch"):
            list(
                ScopeCheckedApi(client).iter_pages(
                    endpoint=RACE_HORSE_CLINIC_ENDPOINT,
                    operation="raceHorseClinic_1",
                    public_params={"meet": 1, "clinic_date": "20260820", "_type": "json"},
                    page_size=1000,
                )
            )


def test_checked_profile_rejects_empty_and_duplicate():
    for items in ([], [profile_payload()["response"]["body"]["items"]["item"][0]] * 2):
        payload = profile_payload()
        payload["response"]["body"].update(items={"item": items}, totalCount=len(items))
        with KraApiClient(
            "test",
            transport=httpx.MockTransport(
                lambda request, payload=payload: httpx.Response(200, json=payload)
            ),
        ) as client:
            with pytest.raises(ValueError):
                list(
                    ScopeCheckedApi(client).iter_pages(
                        endpoint=RACE_HORSE_INFO_ENDPOINT,
                        operation="raceHorseInfo_2",
                        public_params={"meet": 1, "act_gubun": "y", "_type": "json"},
                        page_size=1000,
                    )
                )


def test_duplicate_nullable_medical_and_repeat_keep_one_event(tmp_path):
    factory = migrated_session(tmp_path)
    raw = medical_payload()["response"]["body"]["items"]["item"][0]
    raw.update(hospiName="-", illName2="-")
    item = HorseMedicalItem.model_validate(raw)
    with factory() as session:
        _write_medical(session, [item, item], 100)
        session.commit()
        _write_medical(session, [item], 200)
        session.commit()
        assert session.scalar(select(func.count()).select_from(HorseMedical)) == 1
        assert session.scalar(select(func.count()).select_from(HorseMedicalDiagnosis)) == 1


def test_medical_coverage_detects_missing_but_preserves_old_only_records(tmp_path):
    from horse_racing.jobs.horse_profile_medical import medical_coverage

    factory = migrated_session(tmp_path)
    raw = medical_payload()["response"]["body"]["items"]["item"][0]
    item = HorseMedicalItem.model_validate(raw)
    with factory() as session:
        with pytest.raises(ValueError, match="coverage_mismatch"):
            medical_coverage(session, [item], day=item.clinic_date, meet=item.meet_code)
        _write_medical(session, [item], 100)
        session.commit()
        assert (
            medical_coverage(session, [item, item], day=item.clinic_date, meet=item.meet_code)[
                "source_unique"
            ]
            == 1
        )
        assert (
            medical_coverage(session, [], day=item.clinic_date, meet=item.meet_code)[
                "stored_only_preserved"
            ]
            == 1
        )
        assert session.scalar(select(func.count()).select_from(HorseMedical)) == 1


def test_profile_replay_same_observation_is_one_snapshot(tmp_path):
    factory = migrated_session(tmp_path)
    item = HorseDetailItem.model_validate(profile_payload()["response"]["body"]["items"]["item"][0])
    with factory() as session:
        _write_profiles(session, [item, item], 100, is_active=True)
        session.commit()
        _write_profiles(session, [item], 100, is_active=True)
        session.commit()
        assert session.scalar(select(func.count()).select_from(HorseProfileSnapshot)) == 1
