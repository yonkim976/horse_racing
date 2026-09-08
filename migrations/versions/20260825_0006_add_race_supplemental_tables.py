"""Add race change, equipment, grade, start-training, and steward tables.

Revision ID: 20260825_0006
Revises: 20260825_0005
Create Date: 2026-08-25 12:40:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260825_0006"
down_revision: str | None = "20260825_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "jockey_changes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("horse_id", sa.Integer(), nullable=True),
        sa.Column("meet_code", sa.Integer(), nullable=False),
        sa.Column("race_date_local", sa.Date(), nullable=False),
        sa.Column("race_number", sa.Integer(), nullable=False),
        sa.Column("horse_number", sa.Integer(), nullable=False),
        sa.Column("jockey_before_id", sa.String(length=30), nullable=True),
        sa.Column("jockey_before_name", sa.String(length=100), nullable=True),
        sa.Column("jockey_after_id", sa.String(length=30), nullable=True),
        sa.Column("jockey_after_name", sa.String(length=100), nullable=True),
        sa.Column("carried_weight_before_kg", sa.Float(), nullable=True),
        sa.Column("carried_weight_after_kg", sa.Float(), nullable=True),
        sa.Column("reason", sa.String(length=200), nullable=True),
        sa.Column("observed_at_ms", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["horse_id"], ["horses.id"], name=op.f("fk_jockey_changes_horse_id_horses"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jockey_changes")),
        sa.UniqueConstraint(
            "meet_code",
            "race_date_local",
            "race_number",
            "horse_number",
            "jockey_before_id",
            "jockey_after_id",
            name="uq_jockey_changes_natural",
        ),
    )
    op.create_index(
        "ix_jockey_changes_date_meet",
        "jockey_changes",
        ["race_date_local", "meet_code"],
    )

    op.create_table(
        "race_scratches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("horse_id", sa.Integer(), nullable=True),
        sa.Column("meet_code", sa.Integer(), nullable=False),
        sa.Column("race_date_local", sa.Date(), nullable=False),
        sa.Column("race_number", sa.Integer(), nullable=False),
        sa.Column("horse_number", sa.Integer(), nullable=True),
        sa.Column("reason", sa.String(length=200), nullable=True),
        sa.Column("observed_at_ms", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["horse_id"], ["horses.id"], name=op.f("fk_race_scratches_horse_id_horses"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_race_scratches")),
        sa.UniqueConstraint(
            "meet_code",
            "race_date_local",
            "race_number",
            "horse_id",
            name="uq_race_scratches_natural",
        ),
    )
    op.create_index(
        "ix_race_scratches_date_meet",
        "race_scratches",
        ["race_date_local", "meet_code"],
    )

    op.create_table(
        "entry_equipment",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("horse_id", sa.Integer(), nullable=True),
        sa.Column("meet_code", sa.Integer(), nullable=False),
        sa.Column("race_date_local", sa.Date(), nullable=False),
        sa.Column("race_number", sa.Integer(), nullable=False),
        sa.Column("horse_number", sa.Integer(), nullable=True),
        sa.Column("equipment_raw", sa.String(length=200), nullable=True),
        sa.Column("bleeding_count", sa.Integer(), nullable=True),
        sa.Column("bleeding_date_raw", sa.String(length=40), nullable=True),
        sa.Column("illness_note", sa.String(length=200), nullable=True),
        sa.Column("observed_at_ms", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["horse_id"], ["horses.id"], name=op.f("fk_entry_equipment_horse_id_horses"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_entry_equipment")),
        sa.UniqueConstraint(
            "meet_code",
            "race_date_local",
            "race_number",
            "horse_number",
            name="uq_entry_equipment_natural",
        ),
    )
    op.create_index(
        "ix_entry_equipment_horse_date",
        "entry_equipment",
        ["horse_id", "race_date_local"],
    )

    op.create_table(
        "horse_grade_changes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("horse_id", sa.Integer(), nullable=False),
        sa.Column("meet_code", sa.Integer(), nullable=True),
        sa.Column("blood_type", sa.String(length=50), nullable=True),
        sa.Column("grade_before", sa.String(length=30), nullable=True),
        sa.Column("grade_after", sa.String(length=30), nullable=True),
        sa.Column("start_date_local", sa.Date(), nullable=True),
        sa.Column("end_date_local", sa.Date(), nullable=True),
        sa.Column("observed_at_ms", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["horse_id"], ["horses.id"], name=op.f("fk_horse_grade_changes_horse_id_horses"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_horse_grade_changes")),
        sa.UniqueConstraint(
            "horse_id",
            "start_date_local",
            "grade_before",
            "grade_after",
            name="uq_horse_grade_changes_natural",
        ),
    )
    op.create_index(
        "ix_horse_grade_changes_horse_start",
        "horse_grade_changes",
        ["horse_id", "start_date_local"],
    )

    op.create_table(
        "horse_start_training",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("horse_id", sa.Integer(), nullable=False),
        sa.Column("meet_code", sa.Integer(), nullable=False),
        sa.Column("training_date_local", sa.Date(), nullable=False),
        sa.Column("stable_part", sa.Integer(), nullable=True),
        sa.Column("stable_number", sa.Integer(), nullable=True),
        sa.Column("rider_name", sa.String(length=100), nullable=True),
        sa.Column("remark", sa.String(length=200), nullable=True),
        sa.Column("observed_at_ms", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["horse_id"], ["horses.id"], name=op.f("fk_horse_start_training_horse_id_horses"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_horse_start_training")),
        sa.UniqueConstraint(
            "horse_id",
            "meet_code",
            "training_date_local",
            "stable_part",
            "stable_number",
            "rider_name",
            name="uq_horse_start_training_natural",
        ),
    )
    op.create_index(
        "ix_horse_start_training_horse_date",
        "horse_start_training",
        ["horse_id", "training_date_local"],
    )

    op.create_table(
        "race_steward_reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("meet_code", sa.Integer(), nullable=False),
        sa.Column("race_date_local", sa.Date(), nullable=False),
        sa.Column("race_number", sa.Integer(), nullable=False),
        sa.Column("weather", sa.String(length=100), nullable=True),
        sa.Column("members", sa.Text(), nullable=True),
        sa.Column("judgement", sa.Text(), nullable=True),
        sa.Column("additional_judgement", sa.Text(), nullable=True),
        sa.Column("jockey_change_note", sa.Text(), nullable=True),
        sa.Column("observed_at_ms", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_race_steward_reports")),
        sa.UniqueConstraint(
            "meet_code",
            "race_date_local",
            "race_number",
            name="uq_race_steward_reports_natural",
        ),
    )
    op.create_index(
        "ix_race_steward_reports_date_meet",
        "race_steward_reports",
        ["race_date_local", "meet_code"],
    )


def downgrade() -> None:
    op.drop_index("ix_race_steward_reports_date_meet", table_name="race_steward_reports")
    op.drop_table("race_steward_reports")
    op.drop_index("ix_horse_start_training_horse_date", table_name="horse_start_training")
    op.drop_table("horse_start_training")
    op.drop_index("ix_horse_grade_changes_horse_start", table_name="horse_grade_changes")
    op.drop_table("horse_grade_changes")
    op.drop_index("ix_entry_equipment_horse_date", table_name="entry_equipment")
    op.drop_table("entry_equipment")
    op.drop_index("ix_race_scratches_date_meet", table_name="race_scratches")
    op.drop_table("race_scratches")
    op.drop_index("ix_jockey_changes_date_meet", table_name="jockey_changes")
    op.drop_table("jockey_changes")
