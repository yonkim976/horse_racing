from __future__ import annotations

from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from horse_racing.analysis.features.base import load_source_frames
from horse_racing.db.base import Base
from horse_racing.db.models import (
    EntryEquipment,
    Horse,
    HorseMedical,
    HorseStartTraining,
    HorseTraining,
    JockeyChange,
    Race,
    Racecourse,
    RaceEntry,
    RaceResult,
    RaceSectionResult,
    RaceStewardReport,
    RunningTrial,
    RunningTrialResult,
)


def test_explicit_source_bound_excludes_future_rows_from_every_temporal_source(
    tmp_path,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'bounded-sources.sqlite3'}")
    Base.metadata.create_all(engine)
    cutoff = date(2026, 5, 31)
    future = date(2026, 6, 1)
    with Session(engine) as session:
        horse = Horse(kra_horse_id="bounded-1", name_ko="경계마")
        course = Racecourse(kra_meet_code=1, code="SEOUL", name_ko="서울")
        session.add_all([horse, course])
        session.flush()
        for race_id, race_date in ((1, cutoff), (2, future)):
            race = Race(
                id=race_id,
                racecourse=course,
                race_date_local=race_date,
                race_number=race_id,
                distance_m=1200,
                status="completed",
            )
            entry = RaceEntry(race=race, horse=horse, horse_number=1)
            session.add_all(
                [
                    race,
                    entry,
                    RaceResult(
                        race_entry=entry,
                        finish_position=1,
                        finish_time_ms=76_000,
                    ),
                    RaceSectionResult(
                        race_entry=entry,
                        section_code="G1F",
                        elapsed_time_ms=63_000,
                        time_basis="cumulative",
                        source_kind="fixture",
                    ),
                    RaceStewardReport(
                        meet_code=1,
                        race_date_local=race_date,
                        race_number=race_id,
                        judgement="fixture",
                        observed_at_ms=1,
                    ),
                    HorseTraining(
                        horse=horse,
                        meet_code=1,
                        training_date_local=race_date,
                        observed_at_ms=1,
                    ),
                    HorseStartTraining(
                        horse=horse,
                        meet_code=1,
                        training_date_local=race_date,
                        observed_at_ms=1,
                    ),
                    HorseMedical(
                        horse=horse,
                        meet_code=1,
                        clinic_date_local=race_date,
                        observed_at_ms=1,
                    ),
                    EntryEquipment(
                        horse=horse,
                        meet_code=1,
                        race_date_local=race_date,
                        race_number=race_id,
                        observed_at_ms=1,
                    ),
                    JockeyChange(
                        horse=horse,
                        meet_code=1,
                        race_date_local=race_date,
                        race_number=race_id,
                        horse_number=1,
                        observed_at_ms=1,
                    ),
                ]
            )
            trial = RunningTrial(
                meet_code=1,
                trial_date_local=race_date,
                trial_race_number=race_id,
                distance_m=1000,
                observed_at_ms=1,
            )
            session.add_all(
                [
                    trial,
                    RunningTrialResult(
                        trial=trial,
                        horse=horse,
                        horse_number=1,
                        horse_name_raw="경계마",
                        observed_at_ms=1,
                    ),
                ]
            )
        session.commit()

        sources = load_source_frames(session, race_date_max=cutoff.isoformat())

    for frame, column in (
        (sources.past_results, "race_date"),
        (sources.sections, "race_date"),
        (sources.training, "event_date"),
        (sources.start_training, "event_date"),
        (sources.medical, "event_date"),
        (sources.equipment, "race_date"),
        (sources.jockey_changes, "race_date"),
        (sources.running_trials, "event_date"),
        (sources.steward_reports, "race_date"),
    ):
        assert frame.height == 1
        assert frame[column].max() == cutoff
