from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from horse_racing.db.base import Base
from horse_racing.db.engine import create_engine_for_url
from horse_racing.db.models import (
    Horse,
    Jockey,
    JockeyAffiliationSnapshot,
    Owner,
    Race,
    Racecourse,
    RaceEntry,
    RaceResult,
    Trainer,
    TrainerIdentityResolution,
)
from horse_racing.web import entities
from horse_racing.web.app import create_app


@pytest.fixture
def factory(tmp_path, monkeypatch):
    monkeypatch.setattr(entities, "today_seoul", lambda: date(2026, 10, 9))
    engine = create_engine_for_url(f"sqlite:///{tmp_path / 'jockey.sqlite3'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        session.add_all([
            Jockey(id=1, kra_jockey_id="080361", name_ko="테스트기수", name_en="TEST"),
            Jockey(id=2, kra_jockey_id="080999", name_ko="기록없는기수"),
            Horse(id=1, kra_horse_id="0045769", name_ko="테스트말"),
            Racecourse(id=1, kra_meet_code=4, code="YC", name_ko="영천"),
            Trainer(id=1, kra_trainer_id="070001", name_ko="동명이인"),
            Trainer(id=2, kra_trainer_id="070002", name_ko="동명이인"),
            Owner(id=1, kra_owner_id="050001", name_ko="마주1"),
            Owner(id=2, kra_owner_id="050002", name_ko="마주2"),
            JockeyAffiliationSnapshot(
                jockey_id=1, observed_on=date(2026, 10, 8), meet_code=3,
                official_name_ko="테스트기수", observed_at_ms=1,
                source_url="https://race.kra.co.kr/", source_sha256="a" * 64,
                api_source_url="https://apis.data.go.kr/", api_sha256="b" * 64,
            ),
        ])
        session.commit()
    yield factory
    engine.dispose()


def add_start(session, day, finish=1, *, trainer=1, owner=1,
              status="completed", scratched=False, disqualified=False):
    session.info["race_number"] = session.info.get("race_number", 0) + 1
    race = Race(racecourse_id=1, race_date_local=day,
                race_number=session.info["race_number"], distance_m=1200,
                grade="국6등급", status=status)
    entry = RaceEntry(race=race, horse_id=1, jockey_id=1, trainer_id=trainer,
                      owner_id=owner, horse_number=1, scratched=scratched)
    entry.result = RaceResult(finish_position=finish, disqualified=disqualified,
                              margin_text="½", finish_time_ms=75000 if finish else None)
    session.add(entry)


def test_periods_calendar_years_and_completed_start_exclusions(factory):
    with factory() as session:
        for day, finish in [(date(2026, 9, 9), 1), (date(2026, 9, 8), 2),
                            (date(2026, 10, 9), 3), (date(2025, 10, 9), 1),
                            (date(2025, 10, 8), 2), (date(2024, 1, 1), 3)]:
            add_start(session, day, finish)
        for kwargs in [{"status": "scheduled"}, {"scratched": True}, {"finish": 91},
                       {"finish": None}]:
            add_start(session, date(2026, 10, 1), **kwargs)
        add_start(session, date(2026, 10, 10))  # Future despite completed status.
        add_start(session, date(2026, 10, 1), disqualified=True)
        session.commit()
        detail = entities.load_entity_detail(session, kind_slug="jockeys", official_id="080361")
        data = detail.jockey_detail
        assert data.region == "부산"  # Last race venue is 영천, not the base affiliation.
        month, year, career = [row.stats for row in data.periods]
        assert month[:4] == (3, 1, 0, 1)  # Disqualification counts a start, never a podium.
        assert month.place_rate == "66.7%"
        assert year[:4] == (5, 2, 1, 1)
        assert career[:4] == (7, 2, 2, 2)
        assert [row.label for row in data.years] == ["2026년", "2025년", "2024년"]
        assert [row.stats.starts for row in data.years] == [4, 2, 1]
        assert data.trainers[0].places == 6


def test_partners_merge_only_reviewed_ids_and_use_entire_history(factory):
    with factory() as session:
        session.add(Trainer(id=3, kra_trainer_id="TEMP", name_ko="과거이름"))
        session.flush()
        session.add(TrainerIdentityResolution(
            temporary_trainer_ref="TEMP", official_tr_no="070001", source_name_ko="과거이름",
            canonical_name_ko="동명이인", resolution_status="confirmed", matched_race_rows=1,
            source_reference="test", reviewed_on=date(2026, 10, 8),
        ))
        add_start(session, date(2024, 1, 1), trainer=1, owner=1)
        add_start(session, date(2024, 1, 2), 2, trainer=3, owner=1)
        add_start(session, date(2024, 1, 3), 3, trainer=2, owner=2)
        for _ in range(205):
            add_start(session, date(2026, 10, 1), 8, trainer=2, owner=2)
        session.commit()
        detail = entities.load_entity_detail(session, kind_slug="jockeys", official_id="080361")
        assert len(detail.history) == 200
        data = detail.jockey_detail
        assert data.periods[2].stats.starts == 208
        assert data.years[1].stats.starts == 3
        assert [(row.href, row.places, row.stats.starts) for row in data.trainers] == [
            ("/trainers/070001", 2, 2), ("/trainers/070002", 1, 206),
        ]
        assert [(row.href, row.places) for row in data.owners] == [
            ("/owners/050001", 2), ("/owners/050002", 1),
        ]


def test_detail_tabs_shared_race_formatting_and_empty_data(factory):
    with factory() as session:
        add_start(session, date(2026, 10, 8))
        session.commit()
    with TestClient(create_app(factory)) as client:
        profile = client.get("/jockeys/080361")
        assert profile.status_code == 200
        assert 'aria-label="기수 상세 메뉴"' in profile.text
        assert "기승가능중량" in profile.text
        assert "TEST" in profile.text
        assert 'class="summary-grid"' not in profile.text
        assert 'id="start-history"' not in profile.text
        records = client.get("/jockeys/080361?tab=records")
        assert '<th>조건</th>' in records.text
        assert 'class="horse-record-condition">국6</td>' in records.text
        assert 'class="margin-fraction">½</span>' in records.text
        assert '/horses/0045769' in records.text
        assert 'class="jockey-profile-overview"' not in records.text
        performance = client.get("/jockeys/080361?tab=performance")
        assert 'id="jockey-year-performance"' in performance.text
        assert "2026년" in performance.text
        partners = client.get("/jockeys/080361?tab=partners")
        assert 'href="/trainers/070001"' in partners.text
        assert 'href="/owners/050001"' in partners.text
        assert 'aria-current="page">함께 입상' in partners.text
        assert "기본 정보" in client.get("/jockeys/080361?tab=evaluation").text
        assert client.get("/jockeys/missing?tab=performance").status_code == 404
        assert "집계할 출전 기록이 없습니다" in client.get(
            "/jockeys/080999?tab=performance",
        ).text
        assert "연결된 입상 기록이 없습니다" in client.get(
            "/jockeys/080999?tab=partners",
        ).text


def test_partner_period_filters_change_rankings_and_preserve_other_summaries(factory):
    with factory() as session:
        for day in [date(2024, 1, 1), date(2024, 1, 2),
                    date(2025, 10, 9), date(2026, 9, 8)]:
            add_start(session, day, trainer=1, owner=1)
        add_start(session, date(2026, 9, 9), 2, trainer=2, owner=2)
        add_start(session, date(2026, 10, 9), 3, trainer=2, owner=2)
        session.commit()
        for period, expected in [("career", [(4, 4), (2, 2)]),
                                 ("year", [(2, 2), (2, 2)]), ("month", [(2, 2)])]:
            data = entities.load_entity_detail(
                session, kind_slug="jockeys", official_id="080361", partner_period=period,
            ).jockey_detail
            assert [(r.places, r.stats.starts) for r in data.trainers] == expected
            assert [(r.places, r.stats.starts) for r in data.owners] == expected
            assert data.partner_period == period
            assert data.periods[2].stats.starts == 6  # Summary remains independently scoped.
            if period == "month":
                assert data.trainers[0].href == "/trainers/070002"
                assert data.owners[0].href == "/owners/050002"
                assert data.partner_start == date(2026, 9, 9)
        invalid = entities.load_entity_detail(
            session, kind_slug="jockeys", official_id="080361", partner_period="invalid",
        ).jockey_detail
        assert invalid.partner_period == "career"
    with TestClient(create_app(factory)) as client:
        month = client.get("/jockeys/080361?tab=partners&period=month").text
        assert 'aria-current="page">최근 1개월</a>' in month
        assert 'href="/trainers/070002"' in month
        assert 'href="/trainers/070001"' not in month
        assert "2026.09.09 ~ 2026.10.09" in month
        assert '?tab=records&amp;period=month' in month
        year = client.get("/jockeys/080361?tab=partners&period=year").text
        assert 'aria-current="page">최근 1년</a>' in year
        assert 'href="/trainers/070001"' in year
        default = client.get("/jockeys/080361?tab=partners").text
        assert 'aria-current="page">통산</a>' in default
        assert "통산 동반 입상" in default


def test_profile_displays_stored_debut_and_both_weights_without_birthdate(factory):
    from decimal import Decimal

    with factory() as session:
        profile = session.get(JockeyAffiliationSnapshot, (1, date(2026, 10, 8)))
        profile.debut_date = date(2001, 7, 6)
        profile.riding_weight_own_kg = Decimal("52.5")
        profile.riding_weight_other_kg = Decimal("53")
        session.commit()
        detail = entities.load_entity_detail(session, kind_slug="jockeys", official_id="080361")
        assert detail.jockey_detail.debut_date == "2001.07.06"
        assert detail.jockey_detail.riding_weight == "소속조 52.5kg · 타조 53kg"
        profile.riding_weight_own_kg = Decimal("53")
        session.commit()
        detail = entities.load_entity_detail(session, kind_slug="jockeys", official_id="080361")
        assert detail.jockey_detail.riding_weight == "53kg"
    with TestClient(create_app(factory)) as client:
        html = client.get("/jockeys/080361?tab=profile").text
        assert "2001.07.06" in html
        assert "53kg" in html
        assert "생년월일" not in html
