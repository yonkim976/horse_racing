"""Track historical research-to-operational backfill batches."""

import sqlalchemy as sa
from alembic import op

revision = "20260918_0012"
down_revision = "20260916_0011"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "historical_backfill_batches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("batch_key", sa.String(length=100), nullable=False),
        sa.Column("source_name", sa.String(length=100), nullable=False),
        sa.Column("source_path", sa.Text(), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("cutoff_policy_json", sa.Text(), nullable=False),
        sa.Column("started_at_ms", sa.BigInteger(), nullable=False),
        sa.Column("completed_at_ms", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("records_written_json", sa.Text(), nullable=False),
        sa.Column("validation_json", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'failed')",
            name=op.f("ck_historical_backfill_batches_valid_historical_backfill_status"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_historical_backfill_batches")),
        sa.UniqueConstraint("batch_key", name=op.f("uq_historical_backfill_batches_batch_key")),
    )
    op.create_index(
        "ix_historical_backfill_batches_started",
        "historical_backfill_batches",
        ["started_at_ms"],
    )


def downgrade():
    op.drop_index(
        "ix_historical_backfill_batches_started",
        table_name="historical_backfill_batches",
    )
    op.drop_table("historical_backfill_batches")
