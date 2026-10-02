from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from horse_racing.db.engine import create_engine_for_url

EXPECTED_TABLES = {
    "alembic_version",
    "entry_equipment",
    "entry_equipment_changes",
    "horse_grade_changes",
    "horse_medical",
    "horse_medical_diagnoses",
    "horse_profile_snapshots",
    "horse_rating_snapshots",
    "horse_hill_training",
    "horse_start_training",
    "horse_swim_training",
    "horse_training",
    "horse_weight_history",
    "historical_backfill_batches",
    "horses",
    "ingestion_runs",
    "jockey_changes",
    "jockeys",
    "odds_snapshots",
    "owners",
    "model_predictions",
    "medical_diagnosis_terms",
    "model_prediction_explanations",
    "prediction_outcomes",
    "prediction_model_components",
    "prediction_runs",
    "prediction_settlements",
    "race_entries",
    "race_passing_groups",
    "race_passing_summaries",
    "race_point_source_batches",
    "race_results",
    "race_scratches",
    "race_section_results",
    "race_section_times",
    "race_steward_reports",
    "racecourses",
    "races",
    "running_trial_results",
    "running_trials",
    "source_documents",
    "trainer_affiliation_snapshots",
    "trainer_historical_regions",
    "trainer_identity_resolutions",
    "trainer_people",
    "trainer_person_links",
    "trainer_status_observations",
    "trainers",
}


def test_initial_migration_creates_expected_tables(tmp_path: Path) -> None:
    database_path = tmp_path / "test.sqlite3"
    database_url = f"sqlite:///{database_path}"
    config = Config("alembic.ini")
    config.attributes["database_url"] = database_url
    command.upgrade(config, "head")

    engine = create_engine_for_url(database_url)
    assert set(inspect(engine).get_table_names()) == EXPECTED_TABLES
    with engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert revision == "20261001_0026"
        assert {"equipment_card_raw", "equipment_card_observed_at_ms"} <= {
            c["name"] for c in inspect(engine).get_columns("race_entries")
        }
        assert {"official_tr_no", "observed_on", "status_code", "status_label_ko"} <= {
            c["name"] for c in inspect(engine).get_columns("trainer_status_observations")
        }
        assert {"temporary_trainer_ref", "official_tr_no", "resolution_status"} <= {
            c["name"] for c in inspect(engine).get_columns("trainer_identity_resolutions")
        }
        historical_region_columns = {
            c["name"] for c in inspect(engine).get_columns("trainer_historical_regions")
        }
        assert {
            "trainer_id",
            "region_code",
            "observed_on",
            "source_end_date",
            "retired_list_confirmed",
        } <= historical_region_columns
        affiliation_columns = {
            c["name"] for c in inspect(engine).get_columns("trainer_affiliation_snapshots")
        }
        assert {
            "trainer_id",
            "observed_on",
            "meet_code",
            "stable_part",
            "stats_as_of",
            "source_sha256",
        } <= affiliation_columns
        section_time_columns = {
            c["name"] for c in inspect(engine).get_columns("race_section_times")
        }
        assert {
            "race_entry_id",
            "point_code",
            "time_kind",
            "position_raw",
            "source_batch_id",
        } <= section_time_columns
        passing_group_columns = {
            c["name"] for c in inspect(engine).get_columns("race_passing_groups")
        }
        assert {"race_id", "point_code", "notation_raw", "source_batch_id"} <= passing_group_columns
        columns = {c["name"] for c in inspect(engine).get_columns("race_section_results")}
        assert {"time_basis", "source_kind"} <= columns
        horse_columns = {c["name"] for c in inspect(engine).get_columns("horses")}
        assert {
            "is_active",
            "active_status_observed_at_ms",
            "active_status_source",
        } <= horse_columns
        horse_indexes = {i["name"] for i in inspect(engine).get_indexes("horses")}
        assert "ix_horses_is_active" in horse_indexes
        swim_columns = {c["name"] for c in inspect(engine).get_columns("horse_swim_training")}
        assert {
            "kra_horse_id_raw",
            "swim_count",
            "quality_status",
            "source_document_id",
        } <= swim_columns
        hill_columns = {c["name"] for c in inspect(engine).get_columns("horse_hill_training")}
        assert {
            "farm_entry_reason",
            "quality_status",
            "source_row_hash",
        } <= hill_columns
        passing_columns = {c["name"] for c in inspect(engine).get_columns("race_passing_summaries")}
        assert {
            "race_id",
            "corner_3_raw",
            "corner_4_raw",
            "corner_7_raw",
            "corner_8_raw",
            "tempo_level",
            "source_row_hash",
        } <= passing_columns


def test_sqlite_pragmas_are_enabled(tmp_path: Path) -> None:
    engine = create_engine_for_url(f"sqlite:///{tmp_path / 'pragma.sqlite3'}")
    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
        assert connection.execute(text("PRAGMA journal_mode")).scalar_one() == "wal"
        assert connection.execute(text("PRAGMA busy_timeout")).scalar_one() == 5000


def test_medical_term_migration_backfills_without_rewriting_diagnoses(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'medical_backfill.sqlite3'}"
    config = Config("alembic.ini")
    config.attributes["database_url"] = database_url
    command.upgrade(config, "20260924_0018")
    engine = create_engine_for_url(database_url)
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO horses (id, kra_horse_id, name_ko) VALUES (1, '0000001', '검증마')")
        )
        connection.execute(
            text(
                "INSERT INTO horse_medical "
                "(id, horse_id, meet_code, clinic_date_local, hospital_name, "
                "diagnosis_1, diagnosis_2, observed_at_ms) "
                "VALUES (1, 1, 1, '2026-09-25', '검증병원', "
                "'근육통', '-', 1000), "
                "(2, 1, 1, '2026-09-24', '검증병원', "
                "'근육통', '각막염', 1000)"
            )
        )

    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT diagnosis_1, diagnosis_2 FROM horse_medical ORDER BY id")
        ).all() == [("근육통", "-"), ("근육통", "각막염")]
        assert connection.execute(
            text("SELECT raw_text FROM medical_diagnosis_terms ORDER BY raw_text")
        ).all() == [("각막염",), ("근육통",)]
        assert (
            connection.execute(text("SELECT COUNT(*) FROM horse_medical_diagnoses")).scalar_one()
            == 3
        )
