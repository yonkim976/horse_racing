from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from horse_racing.db.base import Base
from horse_racing.db.models import Horse, HorseStartTraining, HorseTraining, Jockey
from horse_racing.services.training_read import start_training_display_labels, training_display_fields
from horse_racing.web.entities import _load_training as entity_training
from horse_racing.web.race_analysis import _load_training as analysis_training


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Horse(id=1, kra_horse_id="0000001", name_ko="검증마"))
        db.add(Jockey(kra_jockey_id="080001", name_ko="검증기수"))
        db.flush()
        yield db
    engine.dispose()


def training(session, role, number="080001", meet=1):
    row = HorseTraining(
        horse_id=1, meet_code=meet, training_date_local=date(2026, 10, 15),
        rider_type=role, rider_id=number, trainer_name="담당조교사",
        canter_count=0, gallop_count=0, duration_seconds=600, observed_at_ms=1,
    )
    session.add(row)
    session.flush()
    return row


@pytest.mark.parametrize("role,label,status", [
    ("기수", "검증기수", "official_id_reference"),
    ("조교사", "조교사", "role_only"),
    ("조교보", "조교보", "role_only"),
    ("조교승인", "조교승인", "role_only"),
    ("기수후보생", "기수후보생", "role_only"),
    (None, "미확인", "not_available"),
    ("-", "미확인", "not_available"),
])
def test_names_only_for_declared_jockey_even_if_number_matches(session, role, label, status):
    row = training(session, role)
    display = training_display_fields(session, [row])[row.id]
    assert display["rider_display_label"] == label
    assert display["rider_identity_status"] == status
    assert display["rider_name"] == ("검증기수" if role == "기수" else None)
    assert (row.rider_type, row.rider_id, row.trainer_name) == (role, "080001", "담당조교사")


def test_missing_number_does_not_use_responsible_trainer_or_race_jockey(session):
    row = training(session, "기수", number="unknown")
    display = training_display_fields(session, [row])[row.id]
    assert display["rider_name"] is None
    assert display["rider_display_label"] == "기수"
    assert display["rider_identity_status"] == "jockey_name_unresolved"


@pytest.mark.parametrize("raw,expected", [
    ("검증기수", "검증기수"),
    ("검증기수(트)", "기수트랙라이더"),
    ("조", "조교사"), ("(조)", "조교사"),
    ("관", "주로조교"), ("직원명(관)", "주로조교"),
    ("생", "교육생"), ("후", "기수후보생"),
    ("조교보", "조교보"), ("조교승인", "조교승인"),
    ("담당조교사", "미확인"), ("이름미연결", "미확인"),
    ("외", "미확인"), (None, "미확인"),
])
def test_start_training_names_only_for_jockey_references(session, raw, expected):
    row = HorseStartTraining(
        horse_id=1, meet_code=1, training_date_local=date(2026, 10, 15),
        rider_name=raw, observed_at_ms=1,
    )
    session.add(row)
    session.flush()
    assert start_training_display_labels(session, [row])[row.id] == expected
    assert row.rider_name == raw


def test_jeju_unavailable_counts_not_source_zero_and_both_readers_use_labels(session):
    row = training(session, "기수", meet=2)
    display = training_display_fields(session, [row])[row.id]
    assert display["canter_count_display"] is display["gallop_count_display"] is None
    assert (row.canter_count, row.gallop_count) == (0, 0)
    entity = entity_training(session, 1)[0]
    assert (entity.rider, entity.canter, entity.gallop) == ("검증기수", "—", "—")
    rows, _, summary = analysis_training(session, {1}, date(2026, 10, 16))
    assert rows[1][0]["rider_name"] == "검증기수"
    assert rows[1][0]["rider_display_label"] == "검증기수"
    assert rows[1][0]["canter_count"] is None
    assert summary[1]["canter_count"] is None


def test_seoul_zero_counts_remain_zero(session):
    row = training(session, "조교사", meet=1)
    display = training_display_fields(session, [row])[row.id]
    assert display["canter_count_display"] == display["gallop_count_display"] == 0
    assert display["counts_availability_status"] == "source_values"


def test_race_care_keeps_role_separate_from_name(session, monkeypatch):
    from types import SimpleNamespace
    from horse_racing.web.race_care import load_race_care

    monkeypatch.setattr("horse_racing.web.race_care.today_seoul", lambda: date(2026, 10, 16))
    training(session, "기수")
    race = SimpleNamespace(status="scheduled", race_date_local=date(2026, 10, 17), entries=[
        SimpleNamespace(horse_id=1, horse_number=1, horse=session.get(Horse, 1), scratched=False),
    ])
    record = load_race_care(session, race)["horses"][0]["training"][0]
    assert record["rider_type"] == "기수"
    assert record["rider_display_label"] == "검증기수"


def test_web_tables_render_jockey_name_and_roles_without_leaking_other_names(tmp_path):
    from bs4 import BeautifulSoup
    from fastapi.testclient import TestClient
    from test_dashboard import seeded_session
    from horse_racing.db.models import Race
    from horse_racing.web.app import create_app

    factory = seeded_session(tmp_path)
    with factory() as db:
        db.get(Race, 1).status = "scheduled"
        db.add(Jockey(kra_jockey_id="080001", name_ko="검증기수<script>alert(1)</script>"))
        for i, role in enumerate(("기수", "조교사", "조교보", None)):
            db.add(HorseTraining(
                horse_id=1, meet_code=2, training_date_local=date(2026, 8, 20),
                started_at_raw=f"20260820060{i}00", rider_type=role, rider_id="080001",
                duration_seconds=600, canter_count=0, gallop_count=0, observed_at_ms=1,
            ))
        db.commit()
    with TestClient(create_app(factory)) as client:
        response = client.get("/races/1?layout=desktop&tab=training")
        entity = client.get("/horses/003001?tab=history")
    assert response.status_code == entity.status_code == 200
    doc = BeautifulSoup(response.text, "html.parser")
    table = doc.select_one("#race-detail-pane-care .race-care-training .race-care-table")
    assert table is not None
    labels = [x.get_text() for x in table.select("[data-rider-status]")]
    assert labels.count("검증기수<script>alert(1)</script>") == 1
    assert {"조교사", "조교보", "미확인"} <= set(labels)
    assert not table.select("script")
    entity_doc = BeautifulSoup(entity.text, "html.parser")
    assert "기승자" in entity_doc.select_one('[data-pane="training"]').get_text()
    assert not entity_doc.select_one('[data-pane="training"]').select("script")
