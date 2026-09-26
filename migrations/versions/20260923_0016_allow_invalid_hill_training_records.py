"""Preserve malformed official hill records with an explicit quality flag.

Revision ID: 20260923_0016
Revises: 20260923_0015
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260923_0016"
down_revision: str | None = "20260923_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("horse_hill_training") as batch_op:
        batch_op.drop_constraint(
            "valid_quality_status", type_="check"
        )
        batch_op.drop_constraint(
            "nonnegative_f1_seconds", type_="check"
        )
        batch_op.drop_constraint(
            "nonnegative_f2_seconds", type_="check"
        )
        batch_op.drop_constraint(
            "nonnegative_f3_seconds", type_="check"
        )
        batch_op.drop_constraint(
            "nonnegative_total_seconds", type_="check"
        )
        batch_op.create_check_constraint(
            "valid_quality_status",
            "quality_status IN "
            "('valid', 'zero_record', 'incomplete', 'invalid_record')",
        )


def downgrade() -> None:
    with op.batch_alter_table("horse_hill_training") as batch_op:
        batch_op.drop_constraint(
            "valid_quality_status", type_="check"
        )
        batch_op.create_check_constraint(
            "valid_quality_status",
            "quality_status IN ('valid', 'zero_record', 'incomplete')",
        )
        batch_op.create_check_constraint(
            "nonnegative_f1_seconds",
            "f1_seconds IS NULL OR f1_seconds >= 0",
        )
        batch_op.create_check_constraint(
            "nonnegative_f2_seconds",
            "f2_seconds IS NULL OR f2_seconds >= 0",
        )
        batch_op.create_check_constraint(
            "nonnegative_f3_seconds",
            "f3_seconds IS NULL OR f3_seconds >= 0",
        )
        batch_op.create_check_constraint(
            "nonnegative_total_seconds",
            "total_seconds IS NULL OR total_seconds >= 0",
        )
