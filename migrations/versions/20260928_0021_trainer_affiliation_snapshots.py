"""Store dated official trainer stable-part observations.

Revision ID: 20260928_0021
Revises: 20260928_0020
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260928_0021"
down_revision: str | None = "20260928_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trainer_affiliation_snapshots",
        sa.Column("trainer_id", sa.Integer(), nullable=False),
        sa.Column("observed_on", sa.Date(), nullable=False),
        sa.Column("meet_code", sa.SmallInteger(), nullable=False),
        sa.Column("stable_part", sa.SmallInteger(), nullable=False),
        sa.Column("official_name_ko", sa.String(100), nullable=False),
        sa.Column("stats_as_of", sa.Date()),
        sa.Column("observed_at_ms", sa.BigInteger(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.ForeignKeyConstraint(["trainer_id"], ["trainers.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("trainer_id", "observed_on"),
        sa.CheckConstraint("meet_code IN (1, 2, 3)", name="valid_meet_code"),
        sa.CheckConstraint("stable_part BETWEEN 1 AND 99", name="valid_stable_part"),
        sa.CheckConstraint("length(source_sha256) = 64", name="source_sha256_length"),
    )
    op.create_index(
        "ix_trainer_affiliation_snapshots_observed_meet",
        "trainer_affiliation_snapshots",
        ["observed_on", "meet_code"],
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute("alter table public.trainer_affiliation_snapshots enable row level security")
        op.execute(
            "revoke all on public.trainer_affiliation_snapshots from public, anon, authenticated"
        )


def downgrade() -> None:
    op.drop_index(
        "ix_trainer_affiliation_snapshots_observed_meet",
        table_name="trainer_affiliation_snapshots",
    )
    op.drop_table("trainer_affiliation_snapshots")
