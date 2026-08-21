"""Add race-day plan and detailed-result fields.

Revision ID: 20260821_0003
Revises: 20260821_0002
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260821_0003"
down_revision: str | None = "20260821_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("races") as batch_op:
        batch_op.add_column(sa.Column("race_day_count", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("field_size", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("burden_type", sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column("age_condition", sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column("sex_condition", sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column("rating_condition", sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column("newcomer_condition", sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column("actual_start_at_ms", sa.BigInteger(), nullable=True))
        batch_op.add_column(
            sa.Column("start_time_change_reason", sa.String(length=300), nullable=True)
        )

    with op.batch_alter_table("race_entries") as batch_op:
        batch_op.add_column(sa.Column("equipment", sa.Text(), nullable=True))

    with op.batch_alter_table("race_results") as batch_op:
        batch_op.add_column(sa.Column("bonus_prize_money_krw", sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column("rank_remark", sa.String(length=200), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("race_results") as batch_op:
        batch_op.drop_column("rank_remark")
        batch_op.drop_column("bonus_prize_money_krw")

    with op.batch_alter_table("race_entries") as batch_op:
        batch_op.drop_column("equipment")

    with op.batch_alter_table("races") as batch_op:
        batch_op.drop_column("start_time_change_reason")
        batch_op.drop_column("actual_start_at_ms")
        batch_op.drop_column("newcomer_condition")
        batch_op.drop_column("rating_condition")
        batch_op.drop_column("sex_condition")
        batch_op.drop_column("age_condition")
        batch_op.drop_column("burden_type")
        batch_op.drop_column("field_size")
        batch_op.drop_column("race_day_count")
