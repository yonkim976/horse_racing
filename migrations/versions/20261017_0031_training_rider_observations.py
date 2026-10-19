"""Preserve same-event official website rider evidence separately from API rows."""

import sqlalchemy as sa
from alembic import op

revision = "20261017_0031"
down_revision = "20261009_0030"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "horse_training_rider_observations",
        sa.Column(
            "horse_training_id",
            sa.Integer(),
            sa.ForeignKey("horse_training.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "source_document_id",
            sa.Integer(),
            sa.ForeignKey("source_documents.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("source_row_no", sa.Integer(), nullable=False),
        sa.Column("source_fingerprint", sa.String(64), nullable=False),
        sa.Column("rider_label_raw", sa.String(100), nullable=False),
        sa.Column("rider_role", sa.String(30), nullable=False),
        sa.Column("jockey_name", sa.String(100)),
        sa.Column("observed_at_ms", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("length(source_fingerprint) = 64", name="training_rider_fingerprint"),
        sa.CheckConstraint("source_row_no > 0", name="training_rider_source_row"),
        sa.CheckConstraint(
            "rider_role IN ('기수', '조교사', '조교보', '조교승인', '교육생', "
            "'기수후보생', '주로조교', '기수트랙라이더', '미확인')",
            name="training_rider_role",
        ),
        sa.CheckConstraint(
            "rider_role = '기수' OR jockey_name IS NULL", name="training_jockey_only_name"
        ),
    )
    op.create_index(
        "ix_training_rider_source_document",
        "horse_training_rider_observations",
        ["source_document_id"],
    )


def downgrade():
    op.drop_index(
        "ix_training_rider_source_document", table_name="horse_training_rider_observations"
    )
    op.drop_table("horse_training_rider_observations")
