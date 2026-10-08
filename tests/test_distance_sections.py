from __future__ import annotations

from datetime import date
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from horse_racing.db.base import Base
from horse_racing.db.models import (
    Horse,
    IngestionRun,
    Race,
    Racecourse,
    RaceEntry,
    RaceResult,
    RaceSectionResult,
    RunningTrial,
    RunningTrialResult,
    SourceDocument,
)
from horse_racing.services.section_read import SectionObservation
from horse_racing.web.app import create_app
from horse_racing.web.distance_page import load_distance_page
from horse_racing.web.distance_sections import (
    _add_core_metrics,
    _drop_non_monotonic_endpoints,
    _empty_metrics,
    _explicit_endpoint,
    _formatted,
    _intervals,
    _race_point_positions,
    _resolve_endpoints,
    _trial_point_positions,
    _Values,
)


@pytest.fixture
def factory():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    yield factory
    engine.dispose()


def test_average_relative_speed_is_mean_of_individual_ratios_and_two_decimals():
    values = _Values()
    values.add(12_000, distance_m=200, race_distance_m=1200, finish_ms=75_000)
    values.add(13_000, distance_m=200, race_distance_m=1200, finish_ms=90_000)

    assert sum(values.ratios) / len(values.ratios) == pytest.approx(109.7756410256)
    assert _formatted(values, 2)["relative_speed"] == "109.78%"
    assert _formatted(values, 2)["mean_time"] == "12.50"
    assert _formatted(values, 2)["median_time"] == "12.50"


def test_explicit_cumulative_and_closing_basis_and_bad_pair_are_handled():
    closing = SectionObservation(
        race_entry_id=1,
        section_code="G1F",
        elapsed_time_ms=13_000,
        position=None,
        time_basis="closing",
        source_kind="score_sheet",
    )
    cumulative = SectionObservation(
        race_entry_id=1,
        section_code="G3F",
        elapsed_time_ms=55_000,
        position=None,
        time_basis="cumulative",
        source_kind="score_sheet",
        cumulative_time_ms=55_000,
        closing_time_ms=20_000,
    )
    bad_pair = SectionObservation(
        race_entry_id=1,
        section_code="G3F",
        elapsed_time_ms=55_000,
        position=None,
        time_basis="cumulative",
        source_kind="score_sheet",
        cumulative_time_ms=55_000,
        closing_time_ms=19_899,
    )
    unknown = SectionObservation(
        race_entry_id=1,
        section_code="G3F",
        elapsed_time_ms=35_000,
        position=None,
        time_basis=None,
        source_kind="legacy_unknown",
    )

    assert _explicit_endpoint(closing, 75_000)[0] == 62_000
    assert _explicit_endpoint(cumulative, 75_000)[0] == 55_000
    assert _explicit_endpoint(bad_pair, 75_000)[0] is None
    assert _explicit_endpoint(unknown, 75_000)[0] is None


def test_course_endpoint_geometry_only_emits_exact_200m_windows():
    busan_1200 = _race_point_positions(3, 1200)
    assert _intervals(busan_1200, 1200) == [
        (0, 200), (200, 400), (400, 600), (600, 800), (800, 1000), (1000, 1200)
    ]
    seoul_1200 = _race_point_positions(1, 1200)
    assert _intervals(seoul_1200, 1200) == [
        (0, 200), (200, 400), (400, 600), (600, 800), (800, 1000), (1000, 1200)
    ]
    jeju_1110 = _race_point_positions(2, 1110)
    assert jeju_1110["S1F"] == 210
    assert (910, 1110) in _intervals(jeju_1110, 1110)
    assert (0, 210) not in _intervals(jeju_1110, 1110)
    busan_trial = _trial_point_positions(3, 1000)
    assert "G3F" not in busan_trial
    assert _intervals(busan_trial, 1000) == [
        (0, 200), (200, 400), (400, 600), (600, 800), (800, 1000)
    ]


def test_monotonicity_checks_all_pairs_after_outlier_removal():
    endpoints = {0: 0, 200: 50, 400: 100, 600: 30, 800: 40, 1000: 120}

    invalid = _drop_non_monotonic_endpoints(endpoints, 1000)

    assert invalid == {200, 400, 600, 800}
    assert endpoints == {0: 0, 1000: 120}


def test_same_distance_cumulative_and_closing_points_must_agree():
    observations = [
        SectionObservation(
            race_entry_id=1,
            section_code="S1F",
            elapsed_time_ms=15_000,
            position=None,
            time_basis="cumulative",
            source_kind="score_sheet",
            cumulative_time_ms=15_000,
        ),
        SectionObservation(
            race_entry_id=1,
            section_code="G3F",
            elapsed_time_ms=65_000,
            position=None,
            time_basis="closing",
            source_kind="score_sheet",
            closing_time_ms=65_000,
        ),
    ]
    positions = _race_point_positions(3, 800)
    endpoints, metric_points = _resolve_endpoints(observations, positions, 800, 81_000)
    metrics = _empty_metrics()

    _add_core_metrics(
        metrics,
        positions=positions,
        metric_points=metric_points,
        distance_m=800,
        finish_ms=81_000,
    )

    assert 200 not in endpoints
    assert metric_points["S1F"][0] is None
    assert metric_points["G3F"][0] is None
    assert metrics["S1F"].values.times == []
    assert metrics["G3F"].values.times == []


def _source_document(session, *, operation: str | None, suffix: str) -> SourceDocument:
    run = IngestionRun(
        source="kra",
        data_type="running_trial",
        started_at_ms=1,
        status="completed",
    )
    session.add(run)
    session.flush()
    document = SourceDocument(
        ingestion_run_id=run.id,
        source_url=f"https://example.invalid/{suffix}",
        operation=operation,
        requested_at_ms=1,
        retrieved_at_ms=1,
        response_bytes=1,
        local_path=suffix,
        sha256=(suffix.encode().hex() + "0" * 64)[:64],
    )
    session.add(document)
    session.flush()
    return document


def _trial(
    session,
    *,
    meet_code: int = 1,
    trial_date: date,
    race_number: int,
    operation: str | None,
    results: list[tuple[int | None, int | None, str | None, int | None]],
) -> None:
    source = (
        _source_document(session, operation=operation, suffix=f"trial-{trial_date}-{race_number}")
        if operation is not None
        else None
    )
    trial = RunningTrial(
        source_document_id=source.id if source else None,
        meet_code=meet_code,
        trial_date_local=trial_date,
        trial_race_number=race_number,
        distance_m=1000,
        observed_at_ms=1,
    )
    session.add(trial)
    session.flush()
    for number, (position, finish_ms, judgement, g1f_ms) in enumerate(results, start=1):
        session.add(
            RunningTrialResult(
                running_trial_id=trial.id,
                horse_number=number,
                horse_name_raw=f"심사말{number}",
                finish_position=position,
                finish_time_ms=finish_ms,
                judgement=judgement,
                s1f_ms=15_000,
                g3f_ms=41_000,
                g1f_ms=g1f_ms,
                observed_at_ms=1,
            )
        )
    session.flush()


def test_page_filters_races_but_keeps_separate_source_verified_trial_scope(factory):
    with factory() as session:
        course = Racecourse(kra_meet_code=4, code="YEONGCHEON", name_ko="영천")
        seoul = Racecourse(kra_meet_code=1, code="SEOUL", name_ko="서울")
        session.add_all([course, seoul])
        horse = Horse(kra_horse_id="H1", name_ko="테스트말")
        session.add(horse)
        session.flush()
        selected_race = Race(
            racecourse=course,
            race_date_local=date(2026, 8, 1),
            race_number=1,
            distance_m=1200,
            grade="1등급",
            status="completed",
        )
        other_grade = Race(
            racecourse=course,
            race_date_local=date(2026, 8, 1),
            race_number=2,
            distance_m=1200,
            grade="2등급",
            status="completed",
        )
        other_year = Race(
            racecourse=course,
            race_date_local=date(2025, 8, 1),
            race_number=1,
            distance_m=1200,
            grade="1등급",
            status="completed",
        )
        seoul_regular_race = Race(
            racecourse=seoul,
            race_date_local=date(2026, 8, 1),
            race_number=1,
            distance_m=1000,
            grade="국5",
            status="completed",
        )
        session.add_all([selected_race, other_grade, other_year, seoul_regular_race])
        session.flush()
        entry = RaceEntry(race_id=selected_race.id, horse_id=horse.id, horse_number=1)
        session.add(entry)
        session.flush()
        session.add(
            RaceResult(
                race_entry_id=entry.id,
                finish_position=1,
                finish_time_ms=75_000,
                disqualified=False,
            )
        )
        session.add_all(
            [
                RaceSectionResult(
                    race_entry_id=entry.id,
                    section_code="S1F",
                    distance_from_start_m=200,
                    elapsed_time_ms=14_000,
                    time_basis="cumulative",
                    source_kind="score_sheet",
                ),
                RaceSectionResult(
                    race_entry_id=entry.id,
                    section_code="G4F",
                    distance_from_start_m=400,
                    elapsed_time_ms=29_000,
                    time_basis="cumulative",
                    source_kind="score_sheet",
                ),
                RaceSectionResult(
                    race_entry_id=entry.id,
                    section_code="G3F",
                    distance_from_start_m=600,
                    elapsed_time_ms=45_000,
                    time_basis="cumulative",
                    source_kind="score_sheet",
                ),
                RaceSectionResult(
                    race_entry_id=entry.id,
                    section_code="G2F",
                    distance_from_start_m=800,
                    elapsed_time_ms=65_000,
                    time_basis="cumulative",
                    source_kind="score_sheet",
                ),
                RaceSectionResult(
                    race_entry_id=entry.id,
                    section_code="G1F",
                    distance_from_start_m=1000,
                    elapsed_time_ms=62_000,
                    time_basis="cumulative",
                    source_kind="score_sheet",
                ),
            ]
        )
        _trial(
            session,
            trial_date=date(2026, 8, 2),
            race_number=1,
            operation="dacom23",
            results=[
                (1, 65_000, "불", 13_000),
                (2, 70_000, "합", 14_000),
                (None, None, "주", None),
            ],
        )
        _trial(
            session,
            trial_date=date(2026, 8, 3),
            race_number=2,
            operation="other-operation",
            results=[(1, 60_000, "합", 12_000)],
        )
        _trial(
            session,
            trial_date=date(2027, 8, 3),
            race_number=1,
            operation="dacom23",
            results=[(1, 60_000, "합", 12_000)],
        )
        session.commit()

        selected = load_distance_page(
            session,
            year=2026,
            distance=1200,
            grade="1등급",
            page=1,
            meet_code=4,
        )
        assert selected["total"] == 1
        analysis = selected["section_analysis"]
        assert analysis["enabled"] is True
        assert analysis["normal_count"] == 1
        assert analysis["core"][0]["mean_time"] == "14.00"
        assert analysis["core"][1]["mean_time"] == "30.00"
        assert analysis["core"][2]["sample_count"] == 0
        assert any(row["sample_count"] == 0 for row in analysis["intervals"])

        seoul_page = load_distance_page(
            session,
            year=2026,
            distance=1400,
            grade="국5등급",
            page=1,
            meet_code=1,
        )
        assert seoul_page["section_analysis"]["enabled"] is False
        trial = seoul_page["section_analysis"]["trials"][0]
        assert (
            trial["trial_count"],
            trial["verified_trial_count"],
            trial["unverified_trial_count"],
        ) == (2, 1, 1)
        assert trial["normal_count"] == 2
        assert trial["core"][1]["sample_count"] == 2
        assert trial["core"][1]["mean_time"] == "41.00"

        all_scope = load_distance_page(
            session, year=0, distance=0, grade="", page=1, meet_code=1
        )["section_analysis"]
        assert all_scope["enabled"] is False
        assert {row["distance"] for row in all_scope["trials"]} == {1000}
        future = load_distance_page(
            session, year=2027, distance=1400, grade="국5등급", page=1, meet_code=1
        )["section_analysis"]
        assert future["enabled"] is False
        assert future["trials"][0]["verified_trial_count"] == 1

        trial_view = load_distance_page(
            session,
            year=2026,
            distance=1200,
            grade="국5등급",
            page=1,
            meet_code=1,
            view="trials",
        )
        assert trial_view["year"] == 2026
        assert trial_view["years"] == [2027, 2026]
        assert trial_view["distance"] == 0
        assert trial_view["grade"] == ""
        assert "view" not in parse_qs(urlparse(trial_view["all_url"]).query)
        seoul_1000_url = next(
            row["url"] for row in trial_view["distances"] if row["distance"] == 1000
        )
        assert "view" not in parse_qs(urlparse(seoul_1000_url).query)
        assert parse_qs(urlparse(trial_view["meet_urls"]["jeju"]).query) == {
            "view": ["trials"],
            "year": ["2026"],
        }
        default_trial_view = load_distance_page(
            session, year=None, distance=0, grade="", page=1,
            meet_code=1, view="trials",
        )
        assert default_trial_view["year"] == 2027

        client = TestClient(create_app(session_factory=factory))
        response = client.get(
            "/racecourses/seoul/distances?view=trials&year=2026&distance=1200&grade=국5등급"
        )
        assert response.status_code == 200
        assert "주행심사 구간 기록" in response.text
        assert "1,000m 심사" in response.text
        assert "경주 기록" not in response.text
        assert 'name="grade"' not in response.text
        assert 'name="view" value="trials"' in response.text
        assert '<option value="2026" selected>' in response.text
        assert 'href="/racecourses/jeju/distances?view=trials&amp;year=2026"' in response.text
        assert (
            'href="/racecourses/seoul/distances?year=2026&amp;distance=0&amp;grade="'
            in response.text
        )

        regular_response = client.get(trial_view["all_url"])
        assert regular_response.status_code == 200
        assert "경주 기록" in regular_response.text
        assert 'name="view" value="trials"' not in regular_response.text
        distance_response = client.get(seoul_1000_url)
        assert distance_response.status_code == 200
        assert "1,000m 정규 경주" in distance_response.text
        assert "경주 기록" in distance_response.text
        assert 'name="view" value="trials"' not in distance_response.text
