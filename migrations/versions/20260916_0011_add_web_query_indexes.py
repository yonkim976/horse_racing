"""Add bounded web-analysis query indexes."""

from alembic import op

revision = "20260916_0011"
down_revision = "20260908_0010"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "ix_races_status_date_distance_grade",
        "races",
        ["status", "race_date_local", "distance_m", "grade"],
    )
    op.create_index(
        "ix_race_entries_jockey_race",
        "race_entries",
        ["jockey_id", "race_id"],
    )


def downgrade():
    op.drop_index("ix_race_entries_jockey_race", table_name="race_entries")
    op.drop_index("ix_races_status_date_distance_grade", table_name="races")
