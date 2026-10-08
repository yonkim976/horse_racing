"""Store complete dated official active jockey rosters and base affiliations.

Revision ID: 20261008_0027
Revises: 20261001_0026
"""

import sqlalchemy as sa
from alembic import op

revision = "20261008_0027"
down_revision = "20261001_0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "jockey_affiliation_snapshots",
        sa.Column("jockey_id", sa.Integer(), nullable=False),
        sa.Column("observed_on", sa.Date(), nullable=False),
        sa.Column("meet_code", sa.SmallInteger(), nullable=False),
        sa.Column("official_name_ko", sa.String(100), nullable=False),
        sa.Column("observed_at_ms", sa.BigInteger(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("api_source_url", sa.Text(), nullable=False),
        sa.Column("api_sha256", sa.String(64), nullable=False),
        sa.ForeignKeyConstraint(["jockey_id"], ["jockeys.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("jockey_id", "observed_on"),
        sa.CheckConstraint("meet_code IN (1, 2, 3)", name="valid_meet_code"),
        sa.CheckConstraint("length(source_sha256) = 64", name="source_sha256_length"),
        sa.CheckConstraint("length(api_sha256) = 64", name="api_sha256_length"),
    )
    op.create_index(
        "ix_jockey_affiliation_snapshots_observed_meet",
        "jockey_affiliation_snapshots", ["observed_on", "meet_code"],
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute("alter table public.jockey_affiliation_snapshots enable row level security")
        op.execute(
            "revoke all on public.jockey_affiliation_snapshots from public, anon, authenticated"
        )


def downgrade() -> None:
    op.drop_index(
        "ix_jockey_affiliation_snapshots_observed_meet",
        table_name="jockey_affiliation_snapshots",
    )
    op.drop_table("jockey_affiliation_snapshots")
