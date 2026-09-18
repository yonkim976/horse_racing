from pathlib import Path

import pytest

from scripts.generate_supabase_schema import render_schema
from scripts.migrate_sqlite_to_postgres import (
    _partial_target_resume_id,
    _postgres_dsn,
    _validate_source_integer_ranges,
    _validate_source_numeric_types,
    _validate_source_string_lengths,
)

MIGRATION = next(Path("supabase/migrations").glob("*_create_horse_racing_schema.sql"))
HARDENING_MIGRATION = next(
    Path("supabase/migrations").glob("*_harden_prediction_ledger_trigger.sql")
)
WIDENING_MIGRATION = next(
    Path("supabase/migrations").glob("*_widen_legacy_text_fields.sql")
)
PRIZE_MONEY_MIGRATION = next(
    Path("supabase/migrations").glob("*_widen_horse_profile_prize_money.sql")
)
START_TRAINING_MIGRATION = next(
    Path("supabase/migrations").glob("*_widen_start_training_stable_number.sql")
)
FOREIGN_KEY_INDEX_MIGRATION = next(
    Path("supabase/migrations").glob("*_index_remaining_foreign_keys.sql")
)


def test_supabase_schema_is_private_by_default() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    assert sql.count("CREATE TABLE ") == 30
    assert sql.count("ENABLE ROW LEVEL SECURITY") == 1
    assert "FROM PUBLIC, anon, authenticated" in sql
    assert "CREATE POLICY" not in sql
    assert "trg_prediction_runs_immutable" in sql
    assert "NOT is_scored" in sql


def test_generated_schema_includes_enriched_prediction_publication_tables() -> None:
    generated = render_schema()
    assert "CREATE TABLE prediction_model_components" in generated
    assert "CREATE TABLE model_prediction_explanations" in generated
    assert "publication_content_sha256" in generated
    assert "trg_prediction_model_components_immutable" in generated
    assert "trg_model_prediction_explanations_immutable" in generated


def test_prediction_ledger_trigger_has_fixed_search_path() -> None:
    generated = render_schema()
    hardening_sql = HARDENING_MIGRATION.read_text(encoding="utf-8")
    assert "SET search_path = pg_catalog" in generated
    assert "SET search_path = pg_catalog" in hardening_sql


def test_legacy_identifiers_and_status_are_unbounded_text() -> None:
    generated = render_schema()
    widening_sql = WIDENING_MIGRATION.read_text(encoding="utf-8")
    assert "kra_jockey_id TEXT" in generated
    assert "status TEXT NOT NULL" in generated
    assert "track_condition TEXT" in generated
    assert widening_sql.count("TYPE text") == 7


def test_source_string_length_preflight_accepts_frozen_snapshot() -> None:
    import sqlite3

    snapshot = Path("data/backups/after_historical_backfill_20260918.sqlite3")
    with sqlite3.connect(f"file:{snapshot.resolve()}?mode=ro", uri=True) as connection:
        _validate_source_string_lengths(connection)


def test_source_integer_range_preflight_accepts_frozen_snapshot() -> None:
    import sqlite3

    snapshot = Path("data/backups/after_historical_backfill_20260918.sqlite3")
    with sqlite3.connect(f"file:{snapshot.resolve()}?mode=ro", uri=True) as connection:
        _validate_source_integer_ranges(connection)


def test_source_numeric_type_preflight_accepts_frozen_snapshot() -> None:
    import sqlite3

    snapshot = Path("data/backups/after_historical_backfill_20260918.sqlite3")
    with sqlite3.connect(f"file:{snapshot.resolve()}?mode=ro", uri=True) as connection:
        _validate_source_numeric_types(connection)


def test_horse_profile_prize_money_uses_bigint() -> None:
    generated = render_schema()
    migration_sql = PRIZE_MONEY_MIGRATION.read_text(encoding="utf-8")
    assert "prize_money_total_krw BIGINT" in generated
    assert "ALTER COLUMN prize_money_total_krw TYPE bigint" in migration_sql


def test_start_training_stable_number_preserves_text_values() -> None:
    generated = render_schema()
    migration_sql = START_TRAINING_MIGRATION.read_text(encoding="utf-8")
    assert "stable_number TEXT" in generated
    assert "ALTER COLUMN stable_number TYPE text" in migration_sql


def test_remaining_foreign_keys_have_covering_indexes() -> None:
    generated = render_schema()
    migration_sql = FOREIGN_KEY_INDEX_MIGRATION.read_text(encoding="utf-8")
    names = (
        "ix_jockey_changes_horse_id",
        "ix_model_predictions_race_entry_id",
        "ix_race_entries_owner_id",
        "ix_race_entries_trainer_id",
        "ix_race_scratches_horse_id",
        "ix_running_trial_results_jockey_id",
        "ix_running_trial_results_trainer_id",
        "ix_running_trials_source_document_id",
    )
    for name in names:
        assert name in generated
        assert name in migration_sql


class _FakeTarget:
    def __init__(self, bounds: tuple[int | None, int | None]) -> None:
        self.bounds = bounds

    def execute(self, _query):
        return self

    def fetchone(self) -> tuple[int | None, int | None]:
        return self.bounds


def test_partial_load_can_resume_only_from_a_source_id_prefix() -> None:
    import sqlite3

    source = sqlite3.connect(":memory:")
    source.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY)")
    source.executemany("INSERT INTO sample (id) VALUES (?)", [(2,), (4,), (7,)])

    assert (
        _partial_target_resume_id(
            source,
            _FakeTarget((2, 4)),
            schema="public",
            table_name="sample",
            target_count=2,
        )
        == 4
    )

    with pytest.raises(RuntimeError, match="non-prefix partial load"):
        _partial_target_resume_id(
            source,
            _FakeTarget((2, 7)),
            schema="public",
            table_name="sample",
            target_count=2,
        )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("postgres://user:pass@host/db", "postgres://user:pass@host/db"),
        (
            "postgresql+psycopg://user:pass@host/db?sslmode=require",
            "postgresql://user:pass@host/db?sslmode=require",
        ),
    ],
)
def test_postgres_dsn_normalizes_sqlalchemy_scheme(value: str, expected: str) -> None:
    assert _postgres_dsn(value) == expected


def test_postgres_dsn_rejects_non_postgres_url() -> None:
    with pytest.raises(ValueError):
        _postgres_dsn("sqlite:///data/horse_racing.sqlite3")
