"""Add horse profile fields and profile snapshot table.

Revision ID: 20260825_0005
Revises: 20260825_0004
Create Date: 2026-08-25 12:20:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260825_0005"
down_revision: str | None = "20260825_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("horses") as batch:
        batch.add_column(sa.Column("grade", sa.String(length=30), nullable=True))
        batch.add_column(sa.Column("meet_code", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("sire_kra_id", sa.String(length=30), nullable=True))
        batch.add_column(sa.Column("sire_name", sa.String(length=100), nullable=True))
        batch.add_column(sa.Column("dam_kra_id", sa.String(length=30), nullable=True))
        batch.add_column(sa.Column("dam_name", sa.String(length=100), nullable=True))
        batch.add_column(sa.Column("last_sale_amount_raw", sa.String(length=100), nullable=True))
        batch.add_column(sa.Column("profile_observed_at_ms", sa.BigInteger(), nullable=True))

    op.create_table(
        "horse_profile_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("horse_id", sa.Integer(), nullable=False),
        sa.Column("meet_code", sa.Integer(), nullable=True),
        sa.Column("grade", sa.String(length=30), nullable=True),
        sa.Column("rating", sa.Float(), nullable=True),
        sa.Column("race_count_total", sa.Integer(), nullable=True),
        sa.Column("race_count_year", sa.Integer(), nullable=True),
        sa.Column("win_count_total", sa.Integer(), nullable=True),
        sa.Column("win_count_year", sa.Integer(), nullable=True),
        sa.Column("second_count_total", sa.Integer(), nullable=True),
        sa.Column("second_count_year", sa.Integer(), nullable=True),
        sa.Column("third_count_total", sa.Integer(), nullable=True),
        sa.Column("third_count_year", sa.Integer(), nullable=True),
        sa.Column("prize_money_total_krw", sa.Integer(), nullable=True),
        sa.Column("last_sale_amount_raw", sa.String(length=100), nullable=True),
        sa.Column("trainer_kra_id", sa.String(length=30), nullable=True),
        sa.Column("trainer_name", sa.String(length=100), nullable=True),
        sa.Column("owner_kra_id", sa.String(length=30), nullable=True),
        sa.Column("owner_name", sa.String(length=100), nullable=True),
        sa.Column("observed_at_ms", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["horse_id"],
            ["horses.id"],
            name=op.f("fk_horse_profile_snapshots_horse_id_horses"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_horse_profile_snapshots")),
        sa.UniqueConstraint(
            "horse_id",
            "observed_at_ms",
            name="uq_horse_profile_snapshots_horse_observed",
        ),
    )
    op.create_index(
        "ix_horse_profile_snapshots_horse_observed",
        "horse_profile_snapshots",
        ["horse_id", "observed_at_ms"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_horse_profile_snapshots_horse_observed",
        table_name="horse_profile_snapshots",
    )
    op.drop_table("horse_profile_snapshots")
    with op.batch_alter_table("horses") as batch:
        batch.drop_column("profile_observed_at_ms")
        batch.drop_column("last_sale_amount_raw")
        batch.drop_column("dam_name")
        batch.drop_column("dam_kra_id")
        batch.drop_column("sire_name")
        batch.drop_column("sire_kra_id")
        batch.drop_column("meet_code")
        batch.drop_column("grade")
