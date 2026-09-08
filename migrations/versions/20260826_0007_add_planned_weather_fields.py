"""Add pre-race planned weather fields on races.

Revision ID: 20260826_0007
Revises: 20260825_0006
Create Date: 2026-08-26 03:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260826_0007"
down_revision: str | None = "20260825_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("races") as batch_op:
        batch_op.add_column(sa.Column("weather_planned", sa.String(length=30), nullable=True))
        batch_op.add_column(
            sa.Column("track_condition_planned", sa.String(length=30), nullable=True)
        )
        batch_op.add_column(
            sa.Column("track_moisture_percent_planned", sa.Float(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("races") as batch_op:
        batch_op.drop_column("track_moisture_percent_planned")
        batch_op.drop_column("track_condition_planned")
        batch_op.drop_column("weather_planned")
