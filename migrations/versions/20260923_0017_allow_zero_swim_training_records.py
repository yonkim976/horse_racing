"""Preserve official zero-count swimming records with a quality flag.

Revision ID: 20260923_0017
Revises: 20260923_0016
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260923_0017"
down_revision: str | None = "20260923_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("horse_swim_training") as batch_op:
        batch_op.add_column(
            sa.Column(
                "quality_status",
                sa.String(length=20),
                nullable=False,
                server_default="valid",
            )
        )
        batch_op.drop_constraint("positive_swim_count", type_="check")
        batch_op.create_check_constraint(
            "nonnegative_swim_count", "swim_count >= 0"
        )
        batch_op.create_check_constraint(
            "valid_quality_status",
            "quality_status IN ('valid', 'zero_record')",
        )
    with op.batch_alter_table("horse_swim_training") as batch_op:
        batch_op.alter_column("quality_status", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("horse_swim_training") as batch_op:
        batch_op.drop_constraint("valid_quality_status", type_="check")
        batch_op.drop_constraint("nonnegative_swim_count", type_="check")
        batch_op.create_check_constraint("positive_swim_count", "swim_count > 0")
        batch_op.drop_column("quality_status")
