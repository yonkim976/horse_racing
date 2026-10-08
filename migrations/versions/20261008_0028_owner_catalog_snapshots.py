"""Preserve complete regional owner catalog observations without rewriting owners."""

import sqlalchemy as sa
from alembic import op

revision = "20261008_0028"
down_revision = "20261008_0027"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "owner_catalog_snapshots",
        sa.Column("ingestion_run_id", sa.Integer(), nullable=False),
        sa.Column("meet_code", sa.SmallInteger(), nullable=False),
        sa.Column("kra_owner_id", sa.String(6), nullable=False),
        sa.Column("owner_id", sa.Integer()),
        sa.Column("official_name_ko", sa.String(100), nullable=False),
        sa.Column("registration_date", sa.Date()),
        sa.Column("total_registered_horses", sa.Integer(), nullable=False),
        sa.Column("observed_at_ms", sa.BigInteger(), nullable=False),
        sa.Column("source_document_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["ingestion_run_id"], ["ingestion_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["owner_id"], ["owners.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["source_document_id"], ["source_documents.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("ingestion_run_id", "meet_code", "kra_owner_id"),
        sa.CheckConstraint("meet_code IN (1,2,3)", name="valid_meet_code"),
        sa.CheckConstraint("length(kra_owner_id)=6", name="official_owner_id_length"),
        sa.CheckConstraint("total_registered_horses>=0", name="registered_horses_nonnegative"),
    )
    op.create_index(
        "ix_owner_catalog_snapshots_owner_run",
        "owner_catalog_snapshots",
        ["owner_id", "ingestion_run_id"],
    )
    op.create_index(
        "ix_owner_catalog_snapshots_source_document",
        "owner_catalog_snapshots",
        ["source_document_id"],
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute("alter table public.owner_catalog_snapshots enable row level security")
        op.execute("revoke all on public.owner_catalog_snapshots from public, anon, authenticated")


def downgrade():
    op.drop_table("owner_catalog_snapshots")
