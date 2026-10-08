from collections import Counter
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

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
from horse_racing.web import distance_sections
from horse_racing.web.distance_page import load_distance_page


@pytest.fixture
def factory():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    with factory() as session:
        horse = Horse(kra_horse_id="cache-horse", name_ko="캐시 테스트")
        run = IngestionRun(source="kra", data_type="running_trial", started_at_ms=1,
                           status="completed")
        session.add_all([horse, run])
        session.flush()
        document = SourceDocument(
            ingestion_run_id=run.id, source_url="https://example.invalid/trial",
            operation="dacom23", requested_at_ms=1, retrieved_at_ms=1,
            response_bytes=1, local_path="trial", sha256="0" * 64,
        )
        session.add(document)
        session.flush()
        for meet in (1, 3):
            course = Racecourse(kra_meet_code=meet, code=f"MEET{meet}", name_ko=str(meet))
            session.add(course)
            for year in (2025, 2026):
                for grade, times in (("국5", [12000, 13000, 17000]), ("국6", [21000])):
                    for number in range(1, 33 if grade == "국5" else 2):
                        race = Race(
                            racecourse=course, race_date_local=date(year, 8, 1),
                            race_number=number if grade == "국5" else 100,
                            distance_m=1200, grade=grade, status="completed",
                        )
                        session.add(race)
                        if number > len(times):
                            continue
                        entry = RaceEntry(race=race, horse=horse, horse_number=1)
                        session.add(entry)
                        session.flush()
                        session.add(RaceResult(race_entry=entry, finish_position=1,
                                               finish_time_ms=75000, disqualified=False))
                        session.add(RaceSectionResult(
                            race_entry_id=entry.id, section_code="S1F",
                            distance_from_start_m=200,
                            elapsed_time_ms=times[number - 1] + (meet - 1) * 1000,
                            time_basis="cumulative", source_kind="test",
                        ))
                trial = RunningTrial(
                    source_document_id=document.id, meet_code=meet,
                    trial_date_local=date(year, 8, 2), trial_race_number=1,
                    distance_m=1000, observed_at_ms=1,
                )
                session.add(trial)
                session.flush()
                for number, timing in enumerate((14000, 16000, 18000, 1000), start=1):
                    session.add(RunningTrialResult(
                        running_trial_id=trial.id, horse_number=number,
                        horse_name_raw=f"심사{number}", finish_position=number,
                        finish_time_ms=70000, s1f_ms=timing + (meet - 1) * 1000,
                        judgement=" \u3000출\t" if number == 4 else "합", observed_at_ms=1,
                    ))
        session.commit()
    yield factory
    engine.dispose()


class MemoryCache:
    def __init__(self):
        self.values = {}
        self.misses = Counter()

    def __call__(self, key, loader):
        if key not in self.values:
            self.misses[key] += 1
            self.values[key] = loader()
        return self.values[key]


def test_pagination_bands_and_filters_reuse_independent_aggregates(factory, monkeypatch):
    cache = MemoryCache()
    trial_loads = Counter()
    section_loads = []
    original_trials = distance_sections._trial_metrics
    original_sections = distance_sections.load_section_observations

    def trials(session, **kwargs):
        trial_loads[kwargs["meet_code"], kwargs["year"]] += 1
        return original_trials(session, **kwargs)

    def sections(session, entry_ids, **kwargs):
        section_loads.append(tuple(entry_ids))
        return original_sections(session, entry_ids, **kwargs)

    monkeypatch.setattr(distance_sections, "_trial_metrics", trials)
    monkeypatch.setattr(distance_sections, "load_section_observations", sections)
    with factory() as session:
        options = dict(year=None, distance=1200, grade="국5등급", page=1,
                       meet_code=1, cache=cache)
        first = load_distance_page(session, **options)
        second = load_distance_page(session, **(options | {"year": 2026, "page": 2,
                                                          "band": "불량"}))
        assert first["page"] == 1 and second["page"] == 2
        assert first["section_analysis"] == second["section_analysis"]
        assert len(section_loads) == 1
        assert first["section_analysis"]["core"][0]["median_time"] == "13.00"
        assert first["section_analysis"]["core"][0]["mean_time"] == "14.00"
        for changes in ({"grade": "국6등급"}, {"distance": 0, "grade": ""},
                        {"view": "trials", "distance": 0, "grade": ""}):
            load_distance_page(session, **(options | changes))
    assert trial_loads == {(1, 2026): 1}
    assert all(count == 1 for count in cache.misses.values())


def test_cached_results_match_exact_uncached_scopes_including_all_years(factory):
    cache = MemoryCache()
    for meet in (1, 3):
        for year in (2025, 2026, 0):
            for grade in ("국5등급", "국6등급", ""):
                options = dict(year=year, distance=1200, grade=grade, page=1, meet_code=meet)
                with factory() as session:
                    expected = load_distance_page(session, **options)["section_analysis"]
                with factory() as session:
                    actual = load_distance_page(session, **options, cache=cache)["section_analysis"]
                assert actual == expected
                multiplier = 2 if year == 0 else 1
                assert actual["normal_count"] == multiplier * {
                    "국5등급": 3, "국6등급": 1, "": 4,
                }[grade]
                assert actual["trials"][0]["normal_count"] == multiplier * 3
                assert actual["trials"][0]["core"][0]["median_time"] == {
                    1: "16.00", 3: "18.00",
                }[meet]
    assert len([key for key in cache.values if key[0] == "distance-trials"]) == 6
    assert len([key for key in cache.values if key[0] == "distance-race-sections"]) == 18


@pytest.mark.parametrize("judgement", [" 출 ", "\t심\n", "\u3000주\u00a0"])
def test_trial_exclusion_normalizes_upstream_whitespace(judgement):
    assert not distance_sections._trial_result_is_normal(1, 70000, judgement, 4)
