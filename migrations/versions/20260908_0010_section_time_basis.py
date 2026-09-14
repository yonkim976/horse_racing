"""Record section timing semantics and collection source explicitly."""

import sqlalchemy as sa
from alembic import op

revision = "20260908_0010"
down_revision = "20260828_0009"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("race_section_results", sa.Column("time_basis", sa.String(20)))
    op.add_column("race_section_results", sa.Column("source_kind", sa.String(30)))


def downgrade():
    with op.batch_alter_table("race_section_results") as batch:
        batch.drop_column("source_kind")
        batch.drop_column("time_basis")
