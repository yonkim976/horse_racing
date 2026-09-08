"""Add horse rating, weight, training, and medical history tables.

Revision ID: 20260825_0004
Revises: 20260821_0003
Create Date: 2026-08-25 03:20:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260825_0004"
down_revision: str | None = "20260821_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "horse_rating_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("horse_id", sa.Integer(), nullable=False),
        sa.Column("meet_code", sa.Integer(), nullable=True),
        sa.Column("rating_1", sa.Float(), nullable=True),
        sa.Column("rating_2", sa.Float(), nullable=True),
        sa.Column("rating_3", sa.Float(), nullable=True),
        sa.Column("rating_4", sa.Float(), nullable=True),
        sa.Column("observed_at_ms", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["horse_id"], ["horses.id"], name=op.f("fk_horse_rating_snapshots_horse_id_horses"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_horse_rating_snapshots")),
        sa.UniqueConstraint(
            "horse_id",
            "observed_at_ms",
            name="uq_horse_rating_snapshots_horse_observed",
        ),
    )
    op.create_index(
        "ix_horse_rating_snapshots_horse_observed",
        "horse_rating_snapshots",
        ["horse_id", "observed_at_ms"],
    )

    op.create_table(
        "horse_weight_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("horse_id", sa.Integer(), nullable=False),
        sa.Column("meet_code", sa.Integer(), nullable=False),
        sa.Column("race_date_local", sa.Date(), nullable=False),
        sa.Column("race_number", sa.Integer(), nullable=True),
        sa.Column("horse_number", sa.Integer(), nullable=True),
        sa.Column("body_weight_kg", sa.Integer(), nullable=True),
        sa.Column("body_weight_change_kg", sa.Integer(), nullable=True),
        sa.Column("observed_at_ms", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["horse_id"], ["horses.id"], name=op.f("fk_horse_weight_history_horse_id_horses"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_horse_weight_history")),
        sa.UniqueConstraint(
            "horse_id",
            "meet_code",
            "race_date_local",
            "race_number",
            "horse_number",
            name="uq_horse_weight_history_natural",
        ),
    )
    op.create_index(
        "ix_horse_weight_history_horse_date",
        "horse_weight_history",
        ["horse_id", "race_date_local"],
    )

    op.create_table(
        "horse_training",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("horse_id", sa.Integer(), nullable=False),
        sa.Column("meet_code", sa.Integer(), nullable=False),
        sa.Column("training_date_local", sa.Date(), nullable=False),
        sa.Column("stable_part", sa.Integer(), nullable=True),
        sa.Column("stable_number", sa.Integer(), nullable=True),
        sa.Column("trainer_name", sa.String(length=100), nullable=True),
        sa.Column("rider_type", sa.String(length=30), nullable=True),
        sa.Column("rider_id", sa.String(length=30), nullable=True),
        sa.Column("started_at_raw", sa.String(length=20), nullable=True),
        sa.Column("ended_at_raw", sa.String(length=20), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("canter_count", sa.Integer(), nullable=True),
        sa.Column("gallop_count", sa.Integer(), nullable=True),
        sa.Column("entry_plan", sa.String(length=50), nullable=True),
        sa.Column("observed_at_ms", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["horse_id"], ["horses.id"], name=op.f("fk_horse_training_horse_id_horses"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_horse_training")),
        sa.UniqueConstraint(
            "horse_id",
            "meet_code",
            "training_date_local",
            "started_at_raw",
            "ended_at_raw",
            name="uq_horse_training_natural",
        ),
    )
    op.create_index(
        "ix_horse_training_horse_date",
        "horse_training",
        ["horse_id", "training_date_local"],
    )

    op.create_table(
        "horse_medical",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("horse_id", sa.Integer(), nullable=False),
        sa.Column("meet_code", sa.Integer(), nullable=False),
        sa.Column("clinic_date_local", sa.Date(), nullable=False),
        sa.Column("stable_part", sa.Integer(), nullable=True),
        sa.Column("hospital_name", sa.String(length=100), nullable=True),
        sa.Column("diagnosis_1", sa.String(length=200), nullable=True),
        sa.Column("diagnosis_2", sa.String(length=200), nullable=True),
        sa.Column("observed_at_ms", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["horse_id"], ["horses.id"], name=op.f("fk_horse_medical_horse_id_horses"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_horse_medical")),
        sa.UniqueConstraint(
            "horse_id",
            "meet_code",
            "clinic_date_local",
            "hospital_name",
            "diagnosis_1",
            "diagnosis_2",
            name="uq_horse_medical_natural",
        ),
    )
    op.create_index(
        "ix_horse_medical_horse_date",
        "horse_medical",
        ["horse_id", "clinic_date_local"],
    )


def downgrade() -> None:
    op.drop_index("ix_horse_medical_horse_date", table_name="horse_medical")
    op.drop_table("horse_medical")
    op.drop_index("ix_horse_training_horse_date", table_name="horse_training")
    op.drop_table("horse_training")
    op.drop_index("ix_horse_weight_history_horse_date", table_name="horse_weight_history")
    op.drop_table("horse_weight_history")
    op.drop_index("ix_horse_rating_snapshots_horse_observed", table_name="horse_rating_snapshots")
    op.drop_table("horse_rating_snapshots")
