"""Preserve debut dates and both official riding weights in dated jockey profiles."""

import sqlalchemy as sa
from alembic import op

revision = "20261009_0030"
down_revision = "20261009_0029"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("jockey_affiliation_snapshots") as batch:
        batch.add_column(sa.Column("debut_date", sa.Date(), nullable=True))
        batch.add_column(sa.Column("riding_weight_own_kg", sa.Numeric(4, 1), nullable=True))
        batch.add_column(sa.Column("riding_weight_other_kg", sa.Numeric(4, 1), nullable=True))
        batch.create_check_constraint("jockey_profile_debut_valid", "debut_date >= '1900-01-01'")
        for kind in ("own", "other"):
            column = f"riding_weight_{kind}_kg"
            batch.create_check_constraint(
                f"jockey_profile_{kind}_weight_valid", f"{column} > 0 AND {column} < 100",
            )


def downgrade():
    with op.batch_alter_table("jockey_affiliation_snapshots") as batch:
        for name in ("debut", "own_weight", "other_weight"):
            batch.drop_constraint(f"jockey_profile_{name}_valid", type_="check")
        for column in ("debut_date", "riding_weight_own_kg", "riding_weight_other_kg"):
            batch.drop_column(column)
