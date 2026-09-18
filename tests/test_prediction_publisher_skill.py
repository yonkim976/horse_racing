from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import polars as pl
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from horse_racing.db.engine import create_engine_for_url
from horse_racing.db.models import (
    Horse,
    ModelPrediction,
    ModelPredictionExplanation,
    PredictionModelComponent,
    PredictionRun,
    Race,
    Racecourse,
    RaceEntry,
)

PUBLISHED_AT = 2_000_000_000_000


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_skill_publisher_appends_and_reads_back_bundle(tmp_path: Path) -> None:
    database_path = tmp_path / "publisher.sqlite3"
    database_url = f"sqlite:///{database_path}"
    config = Config("alembic.ini")
    config.attributes["database_url"] = database_url
    command.upgrade(config, "head")
    engine = create_engine_for_url(database_url)
    with Session(engine) as session:
        course = Racecourse(kra_meet_code=1, code="SEOUL", name_ko="서울")
        race = Race(
            racecourse=course,
            race_date_local=date(2033, 5, 20),
            race_number=1,
            distance_m=1200,
            scheduled_at_ms=PUBLISHED_AT + 3_600_000,
            status="scheduled",
        )
        for horse_number in (1, 2, 3):
            session.add(
                RaceEntry(
                    race=race,
                    horse=Horse(
                        kra_horse_id=f"90000{horse_number}",
                        name_ko=f"테스트{horse_number}",
                    ),
                    horse_number=horse_number,
                )
            )
        session.add(race)
        session.commit()

    bundle = tmp_path / "bundle"
    bundle.mkdir()
    rows = []
    with Session(engine) as session:
        entries = session.scalars(select(RaceEntry).order_by(RaceEntry.id)).all()
        for rank, entry in enumerate(entries, start=1):
            rows.append(
                {
                    "race_id": entry.race_id,
                    "race_entry_id": entry.id,
                    "horse_number": entry.horse_number,
                    "prob_win": (0.6, 0.3, 0.1)[rank - 1],
                    "prob_top2": (0.8, 0.7, 0.5)[rank - 1],
                    "prob_top3": 1.0,
                    "a_rank_in_race": rank,
                    "field_size": 3,
                    "raw_a_top3_score": 1.0 / rank,
                    "raw_bc_top3_score": 0.5 / rank,
                    "raw_win_score": 0.25 / rank,
                    "runner_identifier": entry.horse.kra_horse_id,
                    "starter_status": "starter",
                    "data_quality_flags_json": "[]",
                }
            )
    pl.DataFrame(rows).write_parquet(bundle / "runner_predictions.parquet")

    explanation_rows = []
    for runner in rows:
        for direction, sign in (("positive", 1.0), ("negative", -1.0)):
            for rank in (1, 2, 3):
                explanation_rows.append(
                    {
                        "race_entry_id": runner["race_entry_id"],
                        "component": "A",
                        "feature_name": f"feature_{direction}_{rank}",
                        "readable_feature_name": f"설명 {direction} {rank}",
                        "feature_value": rank,
                        "field_percentile": rank / 4,
                        "contribution_direction": direction,
                        "contribution_value": sign / rank,
                        "contribution_rank": rank,
                        "explanation_type": "interpretable",
                        "explanation_method": "lightgbm_pred_contrib",
                        "source_cutoff_at_ms": PUBLISHED_AT - 60_000,
                    }
                )
    (bundle / "runner_explanations.json").write_text(
        json.dumps(explanation_rows, ensure_ascii=False),
        encoding="utf-8",
    )

    registry_path = Path("config/prediction_model_registry.json")
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    profile = registry["profiles"]["thoroughbred-main-20260919-v1"]
    artifact_hash = profile["artifacts"]["A_model"]["sha256"]
    metadata_hash = profile["artifacts"]["A_metadata"]["sha256"]
    metadata = {
        "schema_version": 1,
        "domain": "thoroughbred",
        "prediction_stage": "initial_card",
        "experiment_run_id": "61336314-3615-4a87-bc3c-93a90f448c18",
        "model_type": "registered_main_prediction",
        "dataset_version": "test_fixture",
        "as_of_policy": "day_before_18",
        "feature_hash": "a" * 64,
        "model_artifact_sha256": artifact_hash,
        "registry_sha256": _sha256(registry_path),
        "input_card_sha256": "b" * 64,
        "source_card_at_ms": PUBLISHED_AT - 120_000,
        "history_cutoff_date": "2033-05-19",
        "feature_cutoff_at_ms": PUBLISHED_AT - 60_000,
        "data_availability_status": "complete",
        "probability_contract": profile["probability_contract"],
        "combination_algorithm_version": profile["combination_algorithm_version"],
        "components": [
            {
                "component": "A",
                "model_version": profile["components"]["A"]["model_version"],
                "candidate_name": profile["components"]["A"]["candidate"],
                "artifact_sha256": artifact_hash,
                "metadata_sha256": metadata_hash,
                "algorithm_version": "lightgbm_pred_contrib",
                "parameters": {},
            }
        ],
    }
    (bundle / "publication_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False),
        encoding="utf-8",
    )

    environment = os.environ.copy()
    environment["HORSE_RACING_DATABASE_URL"] = database_url
    result = subprocess.run(
        [
            sys.executable,
            ".agents/skills/horse-racing-prediction-publisher/scripts/"
            "publish_prediction_bundle.py",
            str(bundle),
            "--publication-mode",
            "historical",
            "--expected-project-ref",
            "local-test",
            "--confirm-write",
            "--allow-sqlite",
            "--published-at-ms",
            str(PUBLISHED_AT),
        ],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    output = json.loads(result.stdout)
    assert output["ok"] is True
    assert output["runner_rows"] == 3
    assert output["explanation_rows"] == 18

    with Session(engine) as session:
        assert session.scalar(select(func.count(PredictionRun.id))) == 1
        assert session.scalar(select(func.count(ModelPrediction.id))) == 3
        assert session.scalar(select(func.count(PredictionModelComponent.id))) == 1
        assert session.scalar(select(func.count(ModelPredictionExplanation.id))) == 18
