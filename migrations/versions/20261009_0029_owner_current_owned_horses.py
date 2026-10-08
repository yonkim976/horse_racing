"""Preserve official current ownership separately from lifetime registrations."""

import sqlalchemy as sa
from alembic import op

revision = "20261009_0029"
down_revision = "20261008_0028"
branch_labels = None
depends_on = None


def upgrade():
    # Older observations did not ingest this value; unknown must remain null.
    with op.batch_alter_table("owner_catalog_snapshots") as batch:
        batch.add_column(sa.Column("current_owned_horses", sa.Integer(), nullable=True))
        batch.create_check_constraint(
            "current_owned_horses_valid",
            "current_owned_horses >= 0 AND current_owned_horses <= total_registered_horses",
        )


def downgrade():
    with op.batch_alter_table("owner_catalog_snapshots") as batch:
        batch.drop_constraint("current_owned_horses_valid", type_="check")
        batch.drop_column("current_owned_horses")
