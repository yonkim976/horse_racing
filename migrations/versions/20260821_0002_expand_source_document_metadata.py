"""Expand raw source document metadata.

Revision ID: 20260821_0002
Revises: 20260821_0001
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260821_0002"
down_revision: str | None = "20260821_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("source_documents") as batch_op:
        batch_op.drop_constraint("source_url_sha256", type_="unique")
        batch_op.add_column(sa.Column("endpoint", sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column("operation", sa.String(length=100), nullable=True))
        batch_op.add_column(
            sa.Column(
                "request_params_json",
                sa.Text(),
                nullable=False,
                server_default="{}",
            )
        )
        batch_op.add_column(
            sa.Column("requested_at_ms", sa.BigInteger(), nullable=False, server_default="0")
        )
        batch_op.add_column(sa.Column("http_status_code", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("response_bytes", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.create_unique_constraint(
            "ingestion_run_source_url_sha256",
            ["ingestion_run_id", "source_url", "sha256"],
        )
        batch_op.alter_column("request_params_json", server_default=None)
        batch_op.alter_column("requested_at_ms", server_default=None)
        batch_op.alter_column("response_bytes", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("source_documents") as batch_op:
        batch_op.drop_constraint("ingestion_run_source_url_sha256", type_="unique")
        batch_op.drop_column("response_bytes")
        batch_op.drop_column("http_status_code")
        batch_op.drop_column("requested_at_ms")
        batch_op.drop_column("request_params_json")
        batch_op.drop_column("operation")
        batch_op.drop_column("endpoint")
        batch_op.create_unique_constraint("source_url_sha256", ["source_url", "sha256"])
