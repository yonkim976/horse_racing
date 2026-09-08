"""Add running trial race and result tables.

Revision ID: 20260827_0008
Revises: 20260826_0007
Create Date: 2026-08-27 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260827_0008"
down_revision: str | None = "20260826_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "running_trials",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_document_id", sa.Integer(), nullable=True),
        sa.Column("meet_code", sa.Integer(), nullable=False),
        sa.Column("trial_date_local", sa.Date(), nullable=False),
        sa.Column("trial_round", sa.Integer(), nullable=True),
        sa.Column("trial_race_number", sa.Integer(), nullable=False),
        sa.Column("distance_m", sa.Integer(), nullable=False),
        sa.Column("weather", sa.String(length=30), nullable=True),
        sa.Column("track_condition", sa.String(length=30), nullable=True),
        sa.Column("track_moisture_percent", sa.Float(), nullable=True),
        sa.Column("observed_at_ms", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "trial_race_number > 0", name="ck_running_trials_positive_race"
        ),
        sa.CheckConstraint("distance_m > 0", name="ck_running_trials_positive_distance"),
        sa.ForeignKeyConstraint(
            ["source_document_id"],
            ["source_documents.id"],
            name=op.f("fk_running_trials_source_document_id_source_documents"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_running_trials")),
        sa.UniqueConstraint(
            "meet_code",
            "trial_date_local",
            "trial_race_number",
            name="uq_running_trials_natural",
        ),
    )
    op.create_index(
        "ix_running_trials_date_meet",
        "running_trials",
        ["trial_date_local", "meet_code"],
    )

    op.create_table(
        "running_trial_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("running_trial_id", sa.Integer(), nullable=False),
        sa.Column("horse_id", sa.Integer(), nullable=True),
        sa.Column("jockey_id", sa.Integer(), nullable=True),
        sa.Column("trainer_id", sa.Integer(), nullable=True),
        sa.Column("horse_number", sa.Integer(), nullable=False),
        sa.Column("horse_name_raw", sa.String(length=100), nullable=False),
        sa.Column("finish_position", sa.Integer(), nullable=True),
        sa.Column("finish_rank_raw", sa.String(length=10), nullable=True),
        sa.Column("origin_country", sa.String(length=30), nullable=True),
        sa.Column("sex", sa.String(length=20), nullable=True),
        sa.Column("age", sa.Integer(), nullable=True),
        sa.Column("carried_weight_base_kg", sa.Float(), nullable=True),
        sa.Column("carried_weight_extra_kg", sa.Float(), nullable=True),
        sa.Column("carried_weight_raw", sa.String(length=30), nullable=True),
        sa.Column("jockey_name_raw", sa.String(length=100), nullable=True),
        sa.Column("trainer_name_raw", sa.String(length=100), nullable=True),
        sa.Column("body_weight_kg", sa.Integer(), nullable=True),
        sa.Column("finish_time_ms", sa.Integer(), nullable=True),
        sa.Column("margin_text", sa.String(length=50), nullable=True),
        sa.Column("judgement", sa.String(length=20), nullable=True),
        sa.Column("failure_reason", sa.String(length=100), nullable=True),
        sa.Column("inspection_reason", sa.String(length=150), nullable=True),
        sa.Column("g3f_ms", sa.Integer(), nullable=True),
        sa.Column("s1f_ms", sa.Integer(), nullable=True),
        sa.Column("corner_3_ms", sa.Integer(), nullable=True),
        sa.Column("corner_4_ms", sa.Integer(), nullable=True),
        sa.Column("g1f_ms", sa.Integer(), nullable=True),
        sa.Column("section_400_ms", sa.Integer(), nullable=True),
        sa.Column("final_400_ms", sa.Integer(), nullable=True),
        sa.Column("passing_order_raw", sa.String(length=100), nullable=True),
        sa.Column("observed_at_ms", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "horse_number > 0", name="ck_running_trial_results_positive_horse_number"
        ),
        sa.CheckConstraint(
            "finish_position IS NULL OR finish_position > 0",
            name="ck_running_trial_results_positive_finish_position",
        ),
        sa.ForeignKeyConstraint(
            ["horse_id"],
            ["horses.id"],
            name=op.f("fk_running_trial_results_horse_id_horses"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["jockey_id"],
            ["jockeys.id"],
            name=op.f("fk_running_trial_results_jockey_id_jockeys"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["running_trial_id"],
            ["running_trials.id"],
            name=op.f("fk_running_trial_results_running_trial_id_running_trials"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["trainer_id"],
            ["trainers.id"],
            name=op.f("fk_running_trial_results_trainer_id_trainers"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_running_trial_results")),
        sa.UniqueConstraint(
            "running_trial_id",
            "horse_number",
            name="uq_running_trial_results_natural",
        ),
    )
    op.create_index(
        "ix_running_trial_results_horse_trial",
        "running_trial_results",
        ["horse_id", "running_trial_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_running_trial_results_horse_trial", table_name="running_trial_results"
    )
    op.drop_table("running_trial_results")
    op.drop_index("ix_running_trials_date_meet", table_name="running_trials")
    op.drop_table("running_trials")
