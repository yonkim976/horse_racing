from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from horse_racing.db.engine import create_engine_for_url
from horse_racing.db.models import (
    Base,
    Horse,
    HorseRatingSnapshot,
    Race,
    Racecourse,
    RaceEntry,
    RaceResult,
)
from horse_racing.web import entities
from horse_racing.web.app import create_app


@pytest.fixture
def rating_session(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(entities, "today_seoul", lambda: date(2026, 10, 1))
    engine = create_engine_for_url(f"sqlite:///{tmp_path / 'ratings.sqlite3'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        session.add_all(
            [
                Racecourse(kra_meet_code=1, code="SEOUL", name_ko="서울"),
                Racecourse(kra_meet_code=3, code="BUSAN", name_ko="부산경남"),
                Horse(
                    kra_horse_id="0024630",
                    name_ko="올수",
                    is_active=False,
                    active_status_observed_at_ms=1,
                    active_status_source="test:official_roster",
                ),
            ]
        )
        session.commit()
        yield session, factory
    engine.dispose()


def add_start(
    session: Session,
    race_date: date,
    rating: float | None,
    *,
    meet: int = 1,
    status: str = "completed",
    finish: int | None = 5,
    scratched: bool = False,
    disqualified: bool = False,
) -> RaceEntry:
    horse = session.scalar(select(Horse))
    course = session.scalar(select(Racecourse).where(Racecourse.kra_meet_code == meet))
    entry = RaceEntry(
        race=Race(
            racecourse=course,
            race_date_local=race_date,
            race_number=1,
            distance_m=1200,
            status=status,
        ),
        horse=horse,
        horse_number=1,
        rating=rating,
        scratched=scratched,
    )
    session.add(entry)
    session.add(RaceResult(race_entry=entry, finish_position=finish, disqualified=disqualified))
    session.flush()
    return entry


def test_last_race_rating_ignores_api77_future_cards_and_cancellations(rating_session):
    session, factory = rating_session
    horse = session.scalar(select(Horse))
    add_start(session, date(2026, 9, 1), 103)
    add_start(session, date(2026, 9, 10), 82, meet=3)
    add_start(session, date(2026, 9, 15), 500, scratched=True)
    add_start(session, date(2026, 9, 20), 501, finish=91)
    add_start(session, date(2026, 9, 25), 502, finish=None)
    add_start(session, date(2026, 9, 30), 503, status="scheduled", finish=None)
    add_start(session, date(2026, 10, 2), 504)  # Even an invalid future completed row.
    session.add(HorseRatingSnapshot(horse=horse, meet_code=1, rating_4=999, observed_at_ms=1))
    session.commit()

    assert entities._load_horse_list_history(session, [horse.id])[horse.id][0] == "82"
    history = entities._load_ratings(session, horse.id)
    assert [(x.meet_label, x.rating) for x in history] == [("부산경남", "82"), ("서울", "103")]
    assert session.scalar(select(func.count()).select_from(HorseRatingSnapshot)) == 1

    client = TestClient(create_app(session_factory=factory))
    listing = client.get("/horses")
    detail = client.get("/horses/0024630")
    assert listing.status_code == detail.status_code == 200
    assert "마지막 경주 레이팅" in listing.text
    assert "마지막 경주 레이팅" in detail.text
    assert "현재 레이팅" not in detail.text
    assert "2026.09.10 부산경남 1R" in detail.text
    assert "경주 당시 레이팅" in detail.text
    assert "<th>R4</th>" not in detail.text
    assert ">999<" not in listing.text + detail.text


@pytest.mark.parametrize(("value", "label"), [(None, "—"), (0, "—")])
def test_missing_or_zero_last_rating_never_falls_back(rating_session, value, label):
    session, _ = rating_session
    horse = session.scalar(select(Horse))
    add_start(session, date(2026, 9, 1), 90)
    add_start(session, date(2026, 9, 10), value)
    session.add(HorseRatingSnapshot(horse=horse, rating_4=999, observed_at_ms=1))
    session.commit()
    assert entities._load_horse_list_history(session, [horse.id])[horse.id][0] == label
    assert entities._load_ratings(session, horse.id)[0].rating == label


@pytest.mark.parametrize("finish", [91, 92, 94, 95, 99])
def test_excluded_or_cancelled_runner_is_not_last_start(rating_session, finish):
    session, _ = rating_session
    horse = session.scalar(select(Horse))
    add_start(session, date(2026, 9, 1), 80)
    add_start(session, date(2026, 9, 10), 99, finish=finish)
    session.commit()
    assert entities._load_horse_list_history(session, [horse.id])[horse.id][0] == "80"


@pytest.mark.parametrize(("finish", "disqualified"), [(93, False), (96, False), (None, True)])
def test_stopped_or_disqualified_horse_still_has_a_last_start(rating_session, finish, disqualified):
    session, _ = rating_session
    horse = session.scalar(select(Horse))
    add_start(session, date(2026, 9, 1), 80)
    add_start(session, date(2026, 9, 10), 81, finish=finish, disqualified=disqualified)
    session.commit()
    assert entities._load_horse_list_history(session, [horse.id])[horse.id][0] == "81"


def test_unraced_horse_does_not_use_a_future_card_or_api77(rating_session):
    session, _ = rating_session
    horse = session.scalar(select(Horse))
    add_start(session, date(2026, 10, 2), 80, status="scheduled", finish=None)
    session.add(HorseRatingSnapshot(horse=horse, rating_4=999, observed_at_ms=1))
    session.commit()
    assert entities._load_horse_list_history(session, [horse.id])[horse.id][0] == "—"
    assert entities._load_ratings(session, horse.id) == []
