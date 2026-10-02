"""Store source-backed region observations for former trainers.

Revision ID: 20260929_0022
Revises: 20260928_0021
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260929_0022"
down_revision: str | None = "20260928_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trainer_historical_regions",
        sa.Column("trainer_id", sa.Integer(), nullable=False),
        sa.Column("region_code", sa.String(16), nullable=False),
        sa.Column("observed_on", sa.Date(), nullable=False),
        sa.Column("source_end_date", sa.Date(), nullable=False),
        sa.Column("retired_list_confirmed", sa.Boolean(), nullable=False),
        sa.Column("observed_at_ms", sa.BigInteger(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.ForeignKeyConstraint(["trainer_id"], ["trainers.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("trainer_id", "region_code", "observed_on"),
        sa.CheckConstraint(
            "region_code IN ('SEOUL', 'JEJU', 'YEONGNAM')", name="valid_region_code"
        ),
        sa.CheckConstraint("length(source_sha256) = 64", name="source_sha256_length"),
    )
    op.create_index(
        "ix_trainer_historical_regions_region_date",
        "trainer_historical_regions",
        ["region_code", "observed_on"],
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute("alter table public.trainer_historical_regions enable row level security")
        op.execute(
            "revoke all on public.trainer_historical_regions from public, anon, authenticated"
        )


def downgrade() -> None:
    op.drop_index(
        "ix_trainer_historical_regions_region_date", table_name="trainer_historical_regions"
    )
    op.drop_table("trainer_historical_regions")
