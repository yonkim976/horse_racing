"""Store official active or inactive horse status with its evidence."""

import sqlalchemy as sa
from alembic import op

revision = "20260921_0014"
down_revision = "20260919_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("horses", sa.Column("is_active", sa.Boolean(), nullable=True))
    op.add_column(
        "horses",
        sa.Column("active_status_observed_at_ms", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "horses",
        sa.Column("active_status_source", sa.String(length=100), nullable=True),
    )
    op.create_check_constraint(
        "ck_horses_active_status_evidence",
        "horses",
        "(is_active IS NULL AND active_status_observed_at_ms IS NULL "
        "AND active_status_source IS NULL) OR "
        "(is_active IS NOT NULL AND active_status_observed_at_ms > 0 "
        "AND active_status_source IS NOT NULL)",
    ) if op.get_bind().dialect.name == "postgresql" else None
    op.create_index("ix_horses_is_active", "horses", ["is_active"])


def downgrade() -> None:
    op.drop_index("ix_horses_is_active", table_name="horses")
    if op.get_bind().dialect.name == "postgresql":
        op.drop_constraint(
            "ck_horses_active_status_evidence",
            "horses",
            type_="check",
        )
    op.drop_column("horses", "active_status_source")
    op.drop_column("horses", "active_status_observed_at_ms")
    op.drop_column("horses", "is_active")
