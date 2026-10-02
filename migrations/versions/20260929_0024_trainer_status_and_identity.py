"""Store source-backed trainer statuses and non-destructive text-ID resolutions.

Revision ID: 20260929_0024
Revises: 20260929_0023
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260929_0024"
down_revision: str | None = "20260929_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trainer_status_observations",
        sa.Column("official_tr_no", sa.Text(), nullable=False),
        sa.Column("observed_on", sa.Date(), nullable=False),
        sa.Column("canonical_name_ko", sa.Text(), nullable=False),
        sa.Column("region_code", sa.Text(), nullable=False),
        sa.Column("status_code", sa.Text(), nullable=False),
        sa.Column("status_label_ko", sa.Text(), nullable=False),
        sa.Column("source_end_date", sa.Date()),
        sa.Column("classification_basis", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_api_sha256", sa.Text(), nullable=False),
        sa.Column("retired_list_sha256", sa.Text()),
        sa.PrimaryKeyConstraint("official_tr_no", "observed_on"),
        sa.CheckConstraint("region_code IN ('SEOUL', 'JEJU', 'YEONGNAM')", name="valid_region"),
        sa.CheckConstraint(
            "status_code IN ('active', 'retired_confirmed', 'domestic_registration_ended')",
            name="valid_status",
        ),
        sa.CheckConstraint("length(source_api_sha256) = 64", name="valid_api_hash"),
        sa.CheckConstraint(
            "retired_list_sha256 IS NULL OR length(retired_list_sha256) = 64",
            name="valid_retired_hash",
        ),
        sa.CheckConstraint(
            "(status_code = 'active' AND source_end_date IS NULL AND status_label_ko = '현역') "
            "OR (status_code = 'retired_confirmed' AND source_end_date IS NOT NULL "
            "AND status_label_ko = '은퇴 확정') "
            "OR (status_code = 'domestic_registration_ended' "
            "AND source_end_date IS NOT NULL "
            "AND status_label_ko = '국내 등록 종료(은퇴 미확인)')",
            name="status_end_date_label_consistent",
        ),
    )
    op.create_index(
        "ix_trainer_status_observations_status_date",
        "trainer_status_observations",
        ["status_code", "observed_on"],
    )
    op.create_table(
        "trainer_identity_resolutions",
        sa.Column("temporary_trainer_ref", sa.Text(), nullable=False),
        sa.Column("official_tr_no", sa.Text(), nullable=False),
        sa.Column("source_name_ko", sa.Text(), nullable=False),
        sa.Column("canonical_name_ko", sa.Text(), nullable=False),
        sa.Column("resolution_status", sa.Text(), nullable=False),
        sa.Column("matched_race_rows", sa.Integer(), nullable=False),
        sa.Column("source_reference", sa.Text(), nullable=False),
        sa.Column("reviewed_on", sa.Date(), nullable=False),
        sa.PrimaryKeyConstraint("temporary_trainer_ref"),
        sa.ForeignKeyConstraint(
            ["temporary_trainer_ref"], ["trainers.kra_trainer_id"], ondelete="RESTRICT"
        ),
        sa.CheckConstraint(
            "resolution_status IN ('confirmed', 'official_id_candidate')",
            name="valid_resolution_status",
        ),
        sa.CheckConstraint("matched_race_rows > 0", name="positive_matched_race_rows"),
    )
    op.create_index(
        "ix_trainer_identity_resolutions_official_no",
        "trainer_identity_resolutions",
        ["official_tr_no"],
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute("alter table public.trainer_status_observations enable row level security")
        op.execute("alter table public.trainer_identity_resolutions enable row level security")
        op.execute(
            "revoke all on public.trainer_status_observations from public, anon, authenticated"
        )
        op.execute(
            "revoke all on public.trainer_identity_resolutions from public, anon, authenticated"
        )


def downgrade() -> None:
    op.drop_index(
        "ix_trainer_identity_resolutions_official_no",
        table_name="trainer_identity_resolutions",
    )
    op.drop_table("trainer_identity_resolutions")
    op.drop_index(
        "ix_trainer_status_observations_status_date",
        table_name="trainer_status_observations",
    )
    op.drop_table("trainer_status_observations")
