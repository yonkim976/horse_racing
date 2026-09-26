"""Catalog unique medical diagnosis text without changing source records.

Revision ID: 20260925_0019
Revises: 20260924_0018
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260925_0019"
down_revision: str | None = "20260924_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "medical_diagnosis_terms",
        sa.Column("id", sa.Integer(), sa.Identity(always=True), nullable=False),
        sa.Column("raw_text", sa.String(length=200), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_medical_diagnosis_terms")),
        sa.UniqueConstraint("raw_text", name="uq_medical_diagnosis_terms_raw_text"),
    )
    op.create_table(
        "horse_medical_diagnoses",
        sa.Column("horse_medical_id", sa.Integer(), nullable=False),
        sa.Column("source_slot", sa.SmallInteger(), nullable=False),
        sa.Column("term_id", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "source_slot IN (1, 2)",
            name=op.f("ck_horse_medical_diagnoses_valid_source_slot"),
        ),
        sa.ForeignKeyConstraint(
            ["horse_medical_id"],
            ["horse_medical.id"],
            name=op.f("fk_horse_medical_diagnoses_horse_medical_id_horse_medical"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["term_id"],
            ["medical_diagnosis_terms.id"],
            name=op.f("fk_horse_medical_diagnoses_term_id_medical_diagnosis_terms"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "horse_medical_id",
            "source_slot",
            name=op.f("pk_horse_medical_diagnoses"),
        ),
    )
    op.create_index(
        "ix_horse_medical_diagnoses_term_id",
        "horse_medical_diagnoses",
        ["term_id"],
    )

    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            INSERT INTO medical_diagnosis_terms (raw_text)
            SELECT DISTINCT raw_text
            FROM (
                SELECT TRIM(diagnosis_1) AS raw_text FROM horse_medical
                UNION ALL
                SELECT TRIM(diagnosis_2) AS raw_text FROM horse_medical
            ) AS source_terms
            WHERE raw_text IS NOT NULL AND raw_text NOT IN ('', '-')
            """
        )
    )
    for slot in (1, 2):
        connection.execute(
            sa.text(
                f"""
                INSERT INTO horse_medical_diagnoses
                    (horse_medical_id, source_slot, term_id)
                SELECT m.id, {slot}, t.id
                FROM horse_medical AS m
                JOIN medical_diagnosis_terms AS t
                  ON t.raw_text = TRIM(m.diagnosis_{slot})
                WHERE m.diagnosis_{slot} IS NOT NULL
                  AND TRIM(m.diagnosis_{slot}) NOT IN ('', '-')
                """
            )
        )

    if connection.dialect.name == "postgresql":
        op.execute(
            "alter table public.medical_diagnosis_terms enable row level security"
        )
        op.execute(
            "alter table public.horse_medical_diagnoses enable row level security"
        )
        op.execute(
            "revoke all on table public.medical_diagnosis_terms "
            "from public, anon, authenticated"
        )
        op.execute(
            "revoke all on table public.horse_medical_diagnoses "
            "from public, anon, authenticated"
        )
        op.execute(
            "revoke all on sequence public.medical_diagnosis_terms_id_seq "
            "from public, anon, authenticated"
        )


def downgrade() -> None:
    op.drop_index(
        "ix_horse_medical_diagnoses_term_id",
        table_name="horse_medical_diagnoses",
    )
    op.drop_table("horse_medical_diagnoses")
    op.drop_table("medical_diagnosis_terms")
