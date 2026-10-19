from datetime import date

from sqlalchemy import func, select
from test_dashboard import seeded_session

from horse_racing.db.models import HorseMedical, Race
from horse_racing.services.medical_read import medical_display_filter
from horse_racing.web.entities import _count_for_horse, _load_medical
from horse_racing.web.race_care import load_race_care


def test_medical_views_exclude_farriers_before_limits_without_deleting_records(
    tmp_path, monkeypatch
):
    monkeypatch.setattr("horse_racing.web.race_care.today_seoul", lambda: date(2026, 8, 20))
    monkeypatch.setattr("horse_racing.web.race_care.MAX_RECORDS_PER_HORSE", 2)
    monkeypatch.setattr("horse_racing.web.entities.MAX_HORSE_AUX_ROWS", 2)
    factory = seeded_session(tmp_path)
    with factory() as session:
        race = session.get(Race, 1)
        race.status = "scheduled"
        for hospital, diagnosis, day in [
            ("트리플장제", None, 20),
            ("제주경마공원장제소", None, 20),
            ("선진경마장제", "치료장제(제차부란)", 20),
            ("일반동물병원", None, 19),
            (None, "검사", 18),
        ]:
            session.add(
                HorseMedical(
                    horse_id=1,
                    meet_code=2,
                    clinic_date_local=date(2026, 8, day),
                    hospital_name=hospital,
                    diagnosis_1=diagnosis,
                    observed_at_ms=1,
                )
            )
        session.flush()
        original_count = session.scalar(select(func.count()).select_from(HorseMedical))
        rows = _load_medical(session, 1)
        care = load_race_care(session, race)["horses"][0]
        assert [r.hospital for r in rows] == ["일반동물병원", "—"]
        assert [r["hospital"] for r in care["medical"]] == ["일반동물병원", "—"]
        assert care["latest_medical"] == "2026-08-19"
        assert _count_for_horse(session, HorseMedical, 1, medical_display_filter()) == 3
        assert session.scalar(select(func.count()).select_from(HorseMedical)) == original_count
