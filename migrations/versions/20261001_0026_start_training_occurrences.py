"""Preserve separate starting-training source rows, even with identical values."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261001_0026"
down_revision: str | None = "20260930_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "horse_start_training",
        sa.Column("occurrence_no", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "horse_start_training",
        sa.Column("source_kind", sa.String(30), nullable=False, server_default="legacy_api22"),
    )
    op.add_column("horse_start_training", sa.Column("source_document_id", sa.Integer()))
    op.add_column("horse_start_training", sa.Column("source_row_no", sa.Integer()))
    op.add_column("horse_start_training", sa.Column("location_raw", sa.Text()))
    op.execute("""WITH ranked AS (
        SELECT id, row_number() OVER (
            PARTITION BY horse_id,meet_code,training_date_local ORDER BY id) AS n
        FROM horse_start_training
    ) UPDATE horse_start_training SET occurrence_no=(
        SELECT n FROM ranked WHERE ranked.id=horse_start_training.id)""")
    with op.batch_alter_table("horse_start_training") as batch:
        batch.drop_constraint("uq_horse_start_training_natural", type_="unique")
        batch.create_unique_constraint(
            "uq_horse_start_training_occurrence",
            ["horse_id", "meet_code", "training_date_local", "occurrence_no"],
        )
        batch.create_check_constraint("start_training_positive_occurrence", "occurrence_no > 0")
        batch.create_foreign_key(
            "fk_start_training_source_document",
            "source_documents",
            ["source_document_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_index("ix_horse_start_training_source", ["source_document_id"])


def downgrade() -> None:
    raise RuntimeError(
        "A lossy downgrade would collapse preserved source rows; "
        "restore the scoped backup explicitly instead."
    )
