"""Stage canonical passage and section data from meet/year score sheets.

Revision ID: 20260928_0020
Revises: 20260925_0019
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260928_0020"
down_revision: str | None = "20260925_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "race_point_source_batches",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True),
        sa.Column("source_file", sa.Text(), nullable=False, unique=True),
        sa.Column("source_sha256", sa.Text(), nullable=False),
        sa.Column("meet_code", sa.SmallInteger(), nullable=False),
        sa.Column("race_year", sa.SmallInteger(), nullable=False),
        sa.Column("section_row_count", sa.Integer(), nullable=False),
        sa.Column("passing_group_row_count", sa.Integer(), nullable=False),
        sa.Column("loaded_at_ms", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("length(source_sha256) = 64", name="source_sha256_length"),
        sa.CheckConstraint("meet_code BETWEEN 1 AND 4", name="meet_code_range"),
        sa.CheckConstraint("race_year BETWEEN 2000 AND 2100", name="race_year_range"),
        sa.CheckConstraint("section_row_count >= 0", name="section_rows_nonnegative"),
        sa.CheckConstraint("passing_group_row_count >= 0", name="passing_rows_nonnegative"),
        sa.UniqueConstraint(
            "meet_code", "race_year", name="uq_race_point_source_batches_meet_year"
        ),
    )
    op.create_table(
        "race_section_times",
        sa.Column("race_entry_id", sa.Integer(), nullable=False),
        sa.Column("point_code", sa.Text(), nullable=False),
        sa.Column("time_kind", sa.Text(), nullable=False),
        sa.Column("elapsed_time_ms", sa.Integer()),
        sa.Column("position_raw", sa.Integer()),
        sa.Column("source_name", sa.Text(), nullable=False),
        sa.Column("source_field", sa.Text()),
        sa.Column("source_batch_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["race_entry_id"], ["race_entries.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_batch_id"], ["race_point_source_batches.id"]),
        sa.PrimaryKeyConstraint("race_entry_id", "point_code", "time_kind"),
        sa.CheckConstraint(
            "time_kind IN ('cumulative','closing','segment')", name="valid_time_kind"
        ),
        sa.CheckConstraint(
            "elapsed_time_ms IS NULL OR elapsed_time_ms > 0", name="positive_elapsed_time"
        ),
    )
    op.create_index(
        "race_section_times_point_kind_idx",
        "race_section_times",
        ["point_code", "time_kind", "race_entry_id"],
    )
    op.create_index("race_section_times_batch_idx", "race_section_times", ["source_batch_id"])
    op.create_table(
        "race_passing_groups",
        sa.Column("race_id", sa.Integer(), nullable=False),
        sa.Column("point_code", sa.Text(), nullable=False),
        sa.Column("notation_raw", sa.Text(), nullable=False),
        sa.Column("source_batch_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["race_id"], ["races.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_batch_id"], ["race_point_source_batches.id"]),
        sa.PrimaryKeyConstraint("race_id", "point_code"),
    )
    op.create_index("race_passing_groups_batch_idx", "race_passing_groups", ["source_batch_id"])
    if op.get_bind().dialect.name == "postgresql":
        for table in ("race_point_source_batches", "race_section_times", "race_passing_groups"):
            op.execute(f"alter table public.{table} enable row level security")
            op.execute(f"revoke all on public.{table} from public, anon, authenticated")
        op.execute(
            "revoke all on sequence public.race_point_source_batches_id_seq "
            "from public, anon, authenticated"
        )


def downgrade() -> None:
    op.drop_index("race_passing_groups_batch_idx", table_name="race_passing_groups")
    op.drop_table("race_passing_groups")
    op.drop_index("race_section_times_batch_idx", table_name="race_section_times")
    op.drop_index("race_section_times_point_kind_idx", table_name="race_section_times")
    op.drop_table("race_section_times")
    op.drop_table("race_point_source_batches")
