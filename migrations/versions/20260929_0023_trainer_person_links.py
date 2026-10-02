"""Keep visiting-trainer people separate from their KRA registration IDs.

Revision ID: 20260929_0023
Revises: 20260929_0022
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260929_0023"
down_revision: str | None = "20260929_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trainer_people",
        sa.Column("person_key", sa.Text(), primary_key=True),
        sa.Column("canonical_name_en", sa.Text(), nullable=False),
        sa.Column("birth_date", sa.Date()),
        sa.Column("identity_basis", sa.Text(), nullable=False),
        sa.Column("decision_source", sa.Text(), nullable=False),
        sa.Column("decided_on", sa.Date(), nullable=False),
        sa.CheckConstraint(
            "identity_basis IN ('birth_date_and_name', 'english_name_and_visit', 'mixed')",
            name="valid_identity_basis",
        ),
    )
    op.create_table(
        "trainer_person_links",
        sa.Column("trainer_ref", sa.Text(), primary_key=True),
        sa.Column("person_key", sa.Text(), nullable=False),
        sa.Column("ref_kind", sa.Text(), nullable=False),
        sa.Column("name_at_source", sa.Text(), nullable=False),
        sa.Column("link_basis", sa.Text(), nullable=False),
        sa.Column("source_reference", sa.Text(), nullable=False),
        sa.Column("evidence_note", sa.Text()),
        sa.ForeignKeyConstraint(["person_key"], ["trainer_people.person_key"], ondelete="RESTRICT"),
        sa.CheckConstraint(
            "ref_kind IN ('official_tr_no', 'text_ingest_id')",
            name="valid_ref_kind",
        ),
        sa.CheckConstraint(
            "link_basis IN ('birth_date_match', 'english_name_and_visit', "
            "'archived_race_candidate')",
            name="valid_link_basis",
        ),
    )
    op.create_index("ix_trainer_person_links_person_key", "trainer_person_links", ["person_key"])
    if op.get_bind().dialect.name == "postgresql":
        op.execute("alter table public.trainer_people enable row level security")
        op.execute("alter table public.trainer_person_links enable row level security")
        op.execute("revoke all on public.trainer_people from public, anon, authenticated")
        op.execute("revoke all on public.trainer_person_links from public, anon, authenticated")


def downgrade() -> None:
    op.drop_index("ix_trainer_person_links_person_key", table_name="trainer_person_links")
    op.drop_table("trainer_person_links")
    op.drop_table("trainer_people")
