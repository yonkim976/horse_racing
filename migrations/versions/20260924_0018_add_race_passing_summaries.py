"""Add official race-level passing groups and track-tempo summaries.

Revision ID: 20260924_0018
Revises: 20260923_0017
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260924_0018"
down_revision: str | None = "20260923_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _event_id_type() -> sa.types.TypeEngine:
    return sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "race_passing_summaries",
        sa.Column("id", _event_id_type(), sa.Identity(always=True), nullable=False),
        sa.Column("race_id", sa.Integer(), nullable=False),
        sa.Column("source_document_id", sa.Integer(), nullable=True),
        *[
            sa.Column(f"corner_{index}_raw", sa.Text(), nullable=True)
            for index in range(1, 10)
        ],
        sa.Column("pass_time_3f_raw", sa.String(length=20), nullable=True),
        sa.Column("pass_time_4f_raw", sa.String(length=20), nullable=True),
        sa.Column("pass_time_3f_ms", sa.Integer(), nullable=True),
        sa.Column("pass_time_4f_ms", sa.Integer(), nullable=True),
        sa.Column("tempo_raw", sa.String(length=10), nullable=True),
        sa.Column("tempo_level", sa.SmallInteger(), nullable=True),
        sa.Column("quality_status", sa.String(length=20), nullable=False),
        sa.Column("source_row_hash", sa.String(length=64), nullable=False),
        sa.Column("observed_at_ms", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "tempo_level IS NULL OR tempo_level BETWEEN 1 AND 5",
            name=op.f("ck_race_passing_summaries_valid_tempo_level"),
        ),
        sa.CheckConstraint(
            "quality_status IN ('valid', 'incomplete')",
            name=op.f("ck_race_passing_summaries_valid_quality_status"),
        ),
        sa.CheckConstraint(
            "pass_time_3f_ms IS NULL OR pass_time_3f_ms > 0",
            name=op.f("ck_race_passing_summaries_positive_pass_time_3f"),
        ),
        sa.CheckConstraint(
            "pass_time_4f_ms IS NULL OR pass_time_4f_ms > 0",
            name=op.f("ck_race_passing_summaries_positive_pass_time_4f"),
        ),
        sa.ForeignKeyConstraint(
            ["race_id"],
            ["races.id"],
            name=op.f("fk_race_passing_summaries_race_id_races"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id"],
            ["source_documents.id"],
            name=op.f(
                "fk_race_passing_summaries_source_document_id_source_documents"
            ),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_race_passing_summaries")),
        sa.UniqueConstraint("race_id", name="uq_race_passing_summaries_race"),
    )
    op.create_index(
        "ix_race_passing_summaries_source_document",
        "race_passing_summaries",
        ["source_document_id"],
    )
    op.create_index(
        "ix_race_passing_summaries_tempo",
        "race_passing_summaries",
        ["tempo_level"],
    )

    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "alter table public.race_passing_summaries enable row level security"
        )
        op.execute(
            "revoke all on table public.race_passing_summaries "
            "from public, anon, authenticated"
        )
        op.execute(
            "revoke all on sequence public.race_passing_summaries_id_seq "
            "from public, anon, authenticated"
        )


def downgrade() -> None:
    op.drop_index(
        "ix_race_passing_summaries_tempo",
        table_name="race_passing_summaries",
    )
    op.drop_index(
        "ix_race_passing_summaries_source_document",
        table_name="race_passing_summaries",
    )
    op.drop_table("race_passing_summaries")
