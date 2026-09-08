from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, select, update
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import Session, sessionmaker

from horse_racing.db.engine import create_engine_for_url
from horse_racing.db.models import (
    Horse,
    ModelPrediction,
    PredictionOutcome,
    PredictionRun,
    Race,
    Racecourse,
    RaceEntry,
    RaceResult,
)
from horse_racing.services.prediction_ledger import (
    PredictionLedgerError,
    PredictionModelMetadata,
    publish_predictions,
    settle_prediction_run,
    verify_prediction_hash,
)

PUBLISHED_AT = 2_000_000_000_000


def _factory(tmp_path: Path) -> sessionmaker[Session]:
    database_url = f"sqlite:///{tmp_path / 'ledger.sqlite3'}"
    config = Config("alembic.ini")
    config.attributes["database_url"] = database_url
    command.upgrade(config, "head")
    engine = create_engine_for_url(database_url)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        course = Racecourse(kra_meet_code=1, code="SEOUL", name_ko="서울")
        for race_number in (1, 2):
            race = Race(
                racecourse=course,
                race_date_local=date(2033, 5, 20),
                race_number=race_number,
                distance_m=1200,
                scheduled_at_ms=PUBLISHED_AT + race_number * 3_600_000,
                status="scheduled",
            )
            for horse_number in (1, 2, 3):
                horse = Horse(
                    kra_horse_id=f"{race_number}{horse_number:05d}",
                    name_ko=f"테스트{race_number}-{horse_number}",
                )
                session.add(
                    RaceEntry(
                        race=race,
                        horse=horse,
                        horse_number=horse_number,
                    )
                )
            session.add(race)
        session.commit()
    return factory


def _predictions() -> pl.DataFrame:
    rows = []
    entry_id = 1
    for race_id in (1, 2):
        for horse_number, win, top2, top3 in zip(
            (1, 2, 3),
            (0.6, 0.3, 0.1),
            (0.8, 0.7, 0.5),
            (1.0, 1.0, 1.0),
            strict=True,
        ):
            rows.append(
                {
                    "race_id": race_id,
                    "race_entry_id": entry_id,
                    "horse_number": horse_number,
                    "prob_win": win,
                    "prob_top2": top2,
                    "prob_top3": top3,
                }
            )
            entry_id += 1
    return pl.DataFrame(rows)


def _metadata() -> PredictionModelMetadata:
    return PredictionModelMetadata(
        experiment_run_id="61336314-3615-4a87-bc3c-93a90f448c18",
        model_type="probability_ensemble",
        dataset_version="v2_trials/start_minus_30m",
        as_of_policy="start_minus_30m",
        feature_hash="a" * 64,
        model_artifact_sha256="b" * 64,
    )


def _publish(session: Session, predictions: pl.DataFrame | None = None):
    return publish_predictions(
        session,
        _predictions() if predictions is None else predictions,
        metadata=_metadata(),
        feature_cutoff_at_ms=PUBLISHED_AT - 60_000,
        published_at_ms=PUBLISHED_AT,
    )


def test_live_publication_is_complete_hashed_and_immutable(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    with factory() as session:
        summary = _publish(session)
        assert summary.race_count == 2
        assert summary.entry_count == 6
        assert verify_prediction_hash(session, summary.public_id) is True
        assert session.scalar(select(PredictionRun).where(PredictionRun.id == 1)) is not None
        assert len(session.scalars(select(ModelPrediction)).all()) == 6

        with pytest.raises(DatabaseError, match="immutable prediction ledger"):
            session.execute(
                update(PredictionRun)
                .where(PredictionRun.id == 1)
                .values(notes="tampered")
            )
        session.rollback()
        with pytest.raises(DatabaseError, match="immutable prediction ledger"):
            session.execute(delete(ModelPrediction).where(ModelPrediction.id == 1))


def test_publication_rejects_late_incomplete_and_duplicate_payloads(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    with factory() as session:
        with pytest.raises(PredictionLedgerError, match="출발시각 이후"):
            publish_predictions(
                session,
                _predictions(),
                metadata=_metadata(),
                feature_cutoff_at_ms=PUBLISHED_AT,
                published_at_ms=PUBLISHED_AT + 4_000_000,
            )

        with pytest.raises(PredictionLedgerError, match="as-of"):
            publish_predictions(
                session,
                _predictions(),
                metadata=_metadata(),
                feature_cutoff_at_ms=PUBLISHED_AT + 31 * 60_000,
                published_at_ms=PUBLISHED_AT + 31 * 60_000,
            )

        incomplete = (
            _predictions()
            .filter(pl.col("race_entry_id") != 3)
            .with_columns(
                pl.when(pl.col("race_id") == 1)
                .then(pl.when(pl.col("horse_number") == 1).then(2 / 3).otherwise(1 / 3))
                .otherwise(pl.col("prob_win"))
                .alias("prob_win"),
                pl.when(pl.col("race_id") == 1)
                .then(1.0)
                .otherwise(pl.col("prob_top2"))
                .alias("prob_top2"),
            )
        )
        with pytest.raises(PredictionLedgerError, match="출전마 전체"):
            _publish(session, incomplete)

        summary = _publish(session)
        assert summary.publication_mode == "live"
        with pytest.raises(PredictionLedgerError, match="이미 live.*발행"):
            _publish(session)

        revised = _predictions().with_columns(
            pl.when(pl.col("race_id") == 1)
            .then(pl.col("prob_win") * 0.9 + 1 / 30)
            .otherwise(pl.col("prob_win"))
            .alias("prob_win")
        )
        with pytest.raises(PredictionLedgerError, match="다시 발행"):
            _publish(session, revised)


def test_settlement_freezes_metrics_and_cannot_repeat(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    with factory() as session:
        publication = _publish(session)
        races = session.scalars(select(Race).order_by(Race.id)).all()
        for race in races:
            race.status = "completed"
            entries = session.scalars(
                select(RaceEntry)
                .where(RaceEntry.race_id == race.id)
                .order_by(RaceEntry.horse_number)
            ).all()
            for finish_position, entry in enumerate(entries, start=1):
                session.add(
                    RaceResult(
                        race_entry_id=entry.id,
                        finish_position=finish_position,
                    )
                )
        session.commit()

        settlement = settle_prediction_run(
            session,
            publication.public_id,
            settled_at_ms=PUBLISHED_AT + 10_000_000,
        )

        assert settlement.race_count == 2
        assert settlement.entry_count == 6
        assert settlement.excluded_races == 0
        assert settlement.win_log_loss > 0
        assert settlement.win_top1_hit_rate == 1.0
        assert len(session.scalars(select(PredictionOutcome)).all()) == 6
        with pytest.raises(PredictionLedgerError, match="이미 정산"):
            settle_prediction_run(session, publication.public_id)


def test_settlement_excludes_whole_race_after_late_scratch(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    with factory() as session:
        publication = _publish(session)
        races = session.scalars(select(Race).order_by(Race.id)).all()
        for race in races:
            race.status = "completed"
            entries = session.scalars(
                select(RaceEntry)
                .where(RaceEntry.race_id == race.id)
                .order_by(RaceEntry.horse_number)
            ).all()
            for finish_position, entry in enumerate(entries, start=1):
                if race.id == 2 and entry.horse_number == 3:
                    entry.scratched = True
                    continue
                session.add(
                    RaceResult(
                        race_entry_id=entry.id,
                        finish_position=finish_position,
                    )
                )
        session.commit()

        settlement = settle_prediction_run(session, publication.public_id)
        outcomes = session.scalars(select(PredictionOutcome)).all()

        assert settlement.excluded_races == 1
        assert sum(not item.is_scored for item in outcomes) == 3
        assert {
            item.exclusion_reason for item in outcomes if not item.is_scored
        } == {"post_publication_scratch"}


def test_historical_publication_allows_past_races_but_is_labeled(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    with factory() as session:
        summary = publish_predictions(
            session,
            _predictions(),
            metadata=_metadata(),
            feature_cutoff_at_ms=PUBLISHED_AT - 60_000,
            publication_mode="historical",
            published_at_ms=PUBLISHED_AT + 20_000_000,
        )

        assert summary.publication_mode == "historical"
