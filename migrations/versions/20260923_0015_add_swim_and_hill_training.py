"""Add official swimming and hill-track training histories.

Revision ID: 20260923_0015
Revises: 20260921_0014
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260923_0015"
down_revision: str | None = "20260921_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _event_id_type() -> sa.types.TypeEngine:
    return sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "horse_swim_training",
        sa.Column("id", _event_id_type(), sa.Identity(always=True), nullable=False),
        sa.Column("source_document_id", sa.Integer(), nullable=True),
        sa.Column("horse_id", sa.Integer(), nullable=True),
        sa.Column("kra_horse_id_raw", sa.String(length=30), nullable=False),
        sa.Column("horse_name_raw", sa.String(length=100), nullable=False),
        sa.Column("meet_code", sa.SmallInteger(), nullable=False),
        sa.Column("training_date_local", sa.Date(), nullable=False),
        sa.Column("swim_count", sa.SmallInteger(), nullable=False),
        sa.Column("stable_part", sa.SmallInteger(), nullable=True),
        sa.Column("stable_note", sa.Text(), nullable=True),
        sa.Column("trainer_part", sa.SmallInteger(), nullable=True),
        sa.Column("trainer_name", sa.String(length=100), nullable=True),
        sa.Column("observed_at_ms", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "meet_code IN (1, 2, 3, 4)",
            name=op.f("ck_horse_swim_training_valid_meet_code"),
        ),
        sa.CheckConstraint(
            "swim_count > 0",
            name=op.f("ck_horse_swim_training_positive_swim_count"),
        ),
        sa.ForeignKeyConstraint(
            ["horse_id"],
            ["horses.id"],
            name=op.f("fk_horse_swim_training_horse_id_horses"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id"],
            ["source_documents.id"],
            name=op.f(
                "fk_horse_swim_training_source_document_id_source_documents"
            ),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_horse_swim_training")),
        sa.UniqueConstraint(
            "kra_horse_id_raw",
            "meet_code",
            "training_date_local",
            name="uq_horse_swim_training_natural",
        ),
    )
    op.create_index(
        "ix_horse_swim_training_horse_date",
        "horse_swim_training",
        ["horse_id", "training_date_local"],
    )
    op.create_index(
        "ix_horse_swim_training_raw_horse_date",
        "horse_swim_training",
        ["kra_horse_id_raw", "training_date_local"],
    )
    op.create_index(
        "ix_horse_swim_training_source_document",
        "horse_swim_training",
        ["source_document_id"],
    )

    op.create_table(
        "horse_hill_training",
        sa.Column("id", _event_id_type(), sa.Identity(always=True), nullable=False),
        sa.Column("source_document_id", sa.Integer(), nullable=True),
        sa.Column("horse_id", sa.Integer(), nullable=True),
        sa.Column("kra_horse_id_raw", sa.String(length=30), nullable=False),
        sa.Column("horse_name_raw", sa.String(length=100), nullable=False),
        sa.Column("farm_name", sa.String(length=50), nullable=False),
        sa.Column("tag_id", sa.String(length=30), nullable=True),
        sa.Column("chip_id", sa.String(length=30), nullable=True),
        sa.Column("sex_raw", sa.String(length=20), nullable=True),
        sa.Column("birth_date", sa.Date(), nullable=True),
        sa.Column("sire_name_raw", sa.String(length=100), nullable=True),
        sa.Column("dam_name_raw", sa.String(length=100), nullable=True),
        sa.Column("training_operator_name", sa.String(length=100), nullable=True),
        sa.Column("owner_name_raw", sa.String(length=100), nullable=True),
        sa.Column("farm_entry_date", sa.Date(), nullable=True),
        sa.Column("farm_entry_reason", sa.String(length=100), nullable=True),
        sa.Column("training_date_local", sa.Date(), nullable=False),
        sa.Column("training_time_local", sa.Time(), nullable=True),
        sa.Column("f1_seconds", sa.Numeric(precision=6, scale=1), nullable=True),
        sa.Column("f2_seconds", sa.Numeric(precision=6, scale=1), nullable=True),
        sa.Column("f3_seconds", sa.Numeric(precision=6, scale=1), nullable=True),
        sa.Column("total_seconds", sa.Numeric(precision=7, scale=1), nullable=True),
        sa.Column("quality_status", sa.String(length=20), nullable=False),
        sa.Column("source_row_hash", sa.String(length=64), nullable=False),
        sa.Column("observed_at_ms", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "quality_status IN ('valid', 'zero_record', 'incomplete')",
            name=op.f("ck_horse_hill_training_valid_quality_status"),
        ),
        sa.CheckConstraint(
            "f1_seconds IS NULL OR f1_seconds >= 0",
            name=op.f("ck_horse_hill_training_nonnegative_f1_seconds"),
        ),
        sa.CheckConstraint(
            "f2_seconds IS NULL OR f2_seconds >= 0",
            name=op.f("ck_horse_hill_training_nonnegative_f2_seconds"),
        ),
        sa.CheckConstraint(
            "f3_seconds IS NULL OR f3_seconds >= 0",
            name=op.f("ck_horse_hill_training_nonnegative_f3_seconds"),
        ),
        sa.CheckConstraint(
            "total_seconds IS NULL OR total_seconds >= 0",
            name=op.f("ck_horse_hill_training_nonnegative_total_seconds"),
        ),
        sa.ForeignKeyConstraint(
            ["horse_id"],
            ["horses.id"],
            name=op.f("fk_horse_hill_training_horse_id_horses"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id"],
            ["source_documents.id"],
            name=op.f(
                "fk_horse_hill_training_source_document_id_source_documents"
            ),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_horse_hill_training")),
        sa.UniqueConstraint(
            "source_row_hash",
            name="uq_horse_hill_training_source_row_hash",
        ),
    )
    op.create_index(
        "ix_horse_hill_training_horse_date",
        "horse_hill_training",
        ["horse_id", "training_date_local"],
    )
    op.create_index(
        "ix_horse_hill_training_raw_horse_date",
        "horse_hill_training",
        ["kra_horse_id_raw", "training_date_local"],
    )
    op.create_index(
        "ix_horse_hill_training_source_document",
        "horse_hill_training",
        ["source_document_id"],
    )

    if op.get_bind().dialect.name == "postgresql":
        op.execute("alter table public.horse_swim_training enable row level security")
        op.execute("alter table public.horse_hill_training enable row level security")
        op.execute(
            "revoke all on table public.horse_swim_training "
            "from public, anon, authenticated"
        )
        op.execute(
            "revoke all on table public.horse_hill_training "
            "from public, anon, authenticated"
        )
        op.execute(
            "revoke all on sequence public.horse_swim_training_id_seq "
            "from public, anon, authenticated"
        )
        op.execute(
            "revoke all on sequence public.horse_hill_training_id_seq "
            "from public, anon, authenticated"
        )


def downgrade() -> None:
    op.drop_index(
        "ix_horse_hill_training_source_document",
        table_name="horse_hill_training",
    )
    op.drop_index(
        "ix_horse_hill_training_raw_horse_date",
        table_name="horse_hill_training",
    )
    op.drop_index(
        "ix_horse_hill_training_horse_date",
        table_name="horse_hill_training",
    )
    op.drop_table("horse_hill_training")
    op.drop_index(
        "ix_horse_swim_training_source_document",
        table_name="horse_swim_training",
    )
    op.drop_index(
        "ix_horse_swim_training_raw_horse_date",
        table_name="horse_swim_training",
    )
    op.drop_index(
        "ix_horse_swim_training_horse_date",
        table_name="horse_swim_training",
    )
    op.drop_table("horse_swim_training")
