"""Preserve API78 equipment-card text and its explicit + / - marks.

Revision ID: 20260930_0025
Revises: 20260929_0024
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260930_0025"
down_revision: str | None = "20260929_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("race_entries", sa.Column("equipment_card_raw", sa.Text()))
    op.add_column(
        "race_entries", sa.Column("equipment_card_observed_at_ms", sa.BigInteger())
    )
    op.create_table(
        "entry_equipment_changes",
        sa.Column("race_entry_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("equipment_name_raw", sa.Text(), nullable=False),
        sa.Column("change_type", sa.String(length=10), nullable=False),
        sa.Column("observed_at_ms", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("race_entry_id", "position"),
        sa.ForeignKeyConstraint(
            ["race_entry_id"], ["race_entries.id"], ondelete="CASCADE"
        ),
        sa.CheckConstraint("position > 0", name="positive_position"),
        sa.CheckConstraint(
            "change_type IN ('added', 'removed')", name="valid_change_type"
        ),
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute("alter table public.entry_equipment_changes enable row level security")
        op.execute(
            "revoke all on public.entry_equipment_changes from public, anon, authenticated"
        )


def downgrade() -> None:
    op.drop_table("entry_equipment_changes")
    op.drop_column("race_entries", "equipment_card_observed_at_ms")
    op.drop_column("race_entries", "equipment_card_raw")
