"""Add immutable prediction publication and settlement ledger.

Revision ID: 20260828_0009
Revises: 20260827_0008
Create Date: 2026-08-28 01:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260828_0009"
down_revision: str | None = "20260827_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _install_immutable_triggers(table_name: str) -> None:
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        return
    for action in ("UPDATE", "DELETE"):
        trigger = f"trg_{table_name}_no_{action.lower()}"
        op.execute(
            sa.text(
                f"""
                CREATE TRIGGER {trigger}
                BEFORE {action} ON {table_name}
                BEGIN
                    SELECT RAISE(ABORT, 'immutable prediction ledger');
                END
                """
            )
        )


def upgrade() -> None:
    op.create_table(
        "prediction_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("public_id", sa.String(length=36), nullable=False),
        sa.Column("experiment_run_id", sa.String(length=36), nullable=False),
        sa.Column("model_type", sa.String(length=100), nullable=False),
        sa.Column("dataset_version", sa.String(length=100), nullable=False),
        sa.Column("as_of_policy", sa.String(length=50), nullable=False),
        sa.Column("race_date_local", sa.Date(), nullable=False),
        sa.Column("feature_cutoff_at_ms", sa.BigInteger(), nullable=False),
        sa.Column("published_at_ms", sa.BigInteger(), nullable=False),
        sa.Column("publication_mode", sa.String(length=20), nullable=False),
        sa.Column("model_artifact_sha256", sa.String(length=64), nullable=False),
        sa.Column("feature_hash", sa.String(length=64), nullable=False),
        sa.Column("predictions_sha256", sa.String(length=64), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "publication_mode IN ('live', 'historical')",
            name="ck_prediction_runs_publication_mode",
        ),
        sa.CheckConstraint(
            "feature_cutoff_at_ms <= published_at_ms",
            name="ck_prediction_runs_cutoff_before_publication",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_prediction_runs")),
        sa.UniqueConstraint(
            "predictions_sha256",
            name=op.f("uq_prediction_runs_predictions_sha256"),
        ),
        sa.UniqueConstraint("public_id", name=op.f("uq_prediction_runs_public_id")),
    )
    op.create_index(
        "ix_prediction_runs_date_mode",
        "prediction_runs",
        ["race_date_local", "publication_mode"],
    )

    op.create_table(
        "model_predictions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("prediction_run_id", sa.Integer(), nullable=False),
        sa.Column("race_id", sa.Integer(), nullable=False),
        sa.Column("race_entry_id", sa.Integer(), nullable=False),
        sa.Column("horse_number", sa.Integer(), nullable=False),
        sa.Column("prob_win", sa.Float(), nullable=False),
        sa.Column("prob_top2", sa.Float(), nullable=False),
        sa.Column("prob_top3", sa.Float(), nullable=False),
        sa.CheckConstraint("horse_number > 0", name="ck_model_predictions_positive_horse"),
        sa.CheckConstraint(
            "prob_win >= 0 AND prob_win <= 1",
            name="ck_model_predictions_win_probability",
        ),
        sa.CheckConstraint(
            "prob_top2 >= 0 AND prob_top2 <= 1",
            name="ck_model_predictions_top2_probability",
        ),
        sa.CheckConstraint(
            "prob_top3 >= 0 AND prob_top3 <= 1",
            name="ck_model_predictions_top3_probability",
        ),
        sa.ForeignKeyConstraint(
            ["prediction_run_id"],
            ["prediction_runs.id"],
            name=op.f("fk_model_predictions_prediction_run_id_prediction_runs"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["race_entry_id"],
            ["race_entries.id"],
            name=op.f("fk_model_predictions_race_entry_id_race_entries"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["race_id"],
            ["races.id"],
            name=op.f("fk_model_predictions_race_id_races"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_model_predictions")),
        sa.UniqueConstraint(
            "prediction_run_id", "race_entry_id", name="uq_model_predictions_run_entry"
        ),
    )
    op.create_index(
        "ix_model_predictions_race",
        "model_predictions",
        ["race_id", "prediction_run_id"],
    )

    op.create_table(
        "prediction_settlements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("public_id", sa.String(length=36), nullable=False),
        sa.Column("prediction_run_id", sa.Integer(), nullable=False),
        sa.Column("settled_at_ms", sa.BigInteger(), nullable=False),
        sa.Column("outcomes_sha256", sa.String(length=64), nullable=False),
        sa.Column("n_races", sa.Integer(), nullable=False),
        sa.Column("n_entries", sa.Integer(), nullable=False),
        sa.Column("n_excluded_races", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("win_log_loss", sa.Float(), nullable=False),
        sa.Column("win_brier", sa.Float(), nullable=False),
        sa.Column("win_ece", sa.Float(), nullable=False),
        sa.Column("win_top1_hit_rate", sa.Float(), nullable=False),
        sa.Column("win_top3_inclusion_rate", sa.Float(), nullable=False),
        sa.Column("top2_log_loss", sa.Float(), nullable=False),
        sa.Column("top3_log_loss", sa.Float(), nullable=False),
        sa.CheckConstraint("n_races > 0", name="ck_prediction_settlements_positive_races"),
        sa.CheckConstraint("n_entries > 0", name="ck_prediction_settlements_positive_entries"),
        sa.CheckConstraint(
            "n_excluded_races >= 0 AND n_excluded_races < n_races",
            name="ck_prediction_settlements_excluded_races",
        ),
        sa.ForeignKeyConstraint(
            ["prediction_run_id"],
            ["prediction_runs.id"],
            name=op.f("fk_prediction_settlements_prediction_run_id_prediction_runs"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_prediction_settlements")),
        sa.UniqueConstraint(
            "outcomes_sha256",
            name=op.f("uq_prediction_settlements_outcomes_sha256"),
        ),
        sa.UniqueConstraint(
            "prediction_run_id",
            name=op.f("uq_prediction_settlements_prediction_run_id"),
        ),
        sa.UniqueConstraint("public_id", name=op.f("uq_prediction_settlements_public_id")),
    )
    op.create_index(
        "ix_prediction_settlements_settled",
        "prediction_settlements",
        ["settled_at_ms"],
    )

    op.create_table(
        "prediction_outcomes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("settlement_id", sa.Integer(), nullable=False),
        sa.Column("model_prediction_id", sa.Integer(), nullable=False),
        sa.Column("finish_position", sa.Integer(), nullable=True),
        sa.Column("is_scored", sa.Boolean(), nullable=False),
        sa.Column("exclusion_reason", sa.String(length=100), nullable=True),
        sa.Column("win", sa.Boolean(), nullable=True),
        sa.Column("top2", sa.Boolean(), nullable=True),
        sa.Column("top3", sa.Boolean(), nullable=True),
        sa.Column("win_log_loss", sa.Float(), nullable=True),
        sa.CheckConstraint(
            "finish_position IS NULL OR finish_position > 0",
            name="ck_prediction_outcomes_positive_finish",
        ),
        sa.CheckConstraint(
            "(is_scored = 1 AND exclusion_reason IS NULL AND win IS NOT NULL "
            "AND top2 IS NOT NULL AND top3 IS NOT NULL AND win_log_loss IS NOT NULL) "
            "OR (is_scored = 0 AND exclusion_reason IS NOT NULL AND win IS NULL "
            "AND top2 IS NULL AND top3 IS NULL AND win_log_loss IS NULL)",
            name="ck_prediction_outcomes_scoring_state",
        ),
        sa.ForeignKeyConstraint(
            ["model_prediction_id"],
            ["model_predictions.id"],
            name=op.f("fk_prediction_outcomes_model_prediction_id_model_predictions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["settlement_id"],
            ["prediction_settlements.id"],
            name=op.f("fk_prediction_outcomes_settlement_id_prediction_settlements"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_prediction_outcomes")),
        sa.UniqueConstraint(
            "model_prediction_id",
            name=op.f("uq_prediction_outcomes_model_prediction_id"),
        ),
    )
    op.create_index(
        "ix_prediction_outcomes_settlement",
        "prediction_outcomes",
        ["settlement_id"],
    )

    for table_name in (
        "prediction_runs",
        "model_predictions",
        "prediction_settlements",
        "prediction_outcomes",
    ):
        _install_immutable_triggers(table_name)


def downgrade() -> None:
    op.drop_index("ix_prediction_outcomes_settlement", table_name="prediction_outcomes")
    op.drop_table("prediction_outcomes")
    op.drop_index("ix_prediction_settlements_settled", table_name="prediction_settlements")
    op.drop_table("prediction_settlements")
    op.drop_index("ix_model_predictions_race", table_name="model_predictions")
    op.drop_table("model_predictions")
    op.drop_index("ix_prediction_runs_date_mode", table_name="prediction_runs")
    op.drop_table("prediction_runs")
