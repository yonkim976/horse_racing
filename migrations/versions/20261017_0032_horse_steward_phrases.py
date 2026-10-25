"""Attach verified literal steward phrases to operational horses and races."""
import sqlalchemy as sa
from alembic import op

revision = "20261017_0032"
down_revision = "20261017_0031"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "horse_steward_phrases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("horse_id", sa.Integer(), sa.ForeignKey("horses.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("race_id", sa.Integer(), sa.ForeignKey("races.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("race_entry_id", sa.Integer(), sa.ForeignKey("race_entries.id", ondelete="RESTRICT")),
        sa.Column("race_steward_report_id", sa.Integer(), sa.ForeignKey("race_steward_reports.id", ondelete="RESTRICT")),
        sa.Column("historical_program", sa.Integer(), nullable=False),
        sa.Column("phrase_text", sa.Text(), nullable=False),
        sa.Column("phrase_sha256", sa.String(64), nullable=False),
        sa.Column("text_basis", sa.String(30), nullable=False, server_default="official_website"),
        sa.Column("website_text_verified", sa.Boolean(), nullable=False),
        sa.Column("entry_link_status", sa.String(30), nullable=False),
        sa.Column("provenance_json", sa.Text(), nullable=False),
        sa.Column("source_dataset_sha256", sa.String(64), nullable=False),
        sa.Column("source_dataset_path", sa.Text(), nullable=False),
        sa.Column("first_observed_at_ms", sa.BigInteger(), nullable=False),
        sa.Column("last_observed_at_ms", sa.BigInteger(), nullable=False),
        sa.Column("source_published_at_ms", sa.BigInteger()),
        sa.Column("historical_publication_time_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("ingested_at_ms", sa.BigInteger(), nullable=False),
        sa.UniqueConstraint("horse_id", "race_id", "phrase_sha256", name="uq_horse_steward_phrases_content"),
        sa.CheckConstraint("historical_program > 0", name="positive_steward_program"),
        sa.CheckConstraint("length(trim(phrase_text)) > 0", name="nonempty_steward_phrase"),
        sa.CheckConstraint("text_basis = 'official_website'", name="official_steward_wording"),
        sa.CheckConstraint("website_text_verified", name="verified_steward_wording"),
        sa.CheckConstraint(
            "(entry_link_status = 'matched' AND race_entry_id IS NOT NULL) OR "
            "(entry_link_status = 'entry_missing' AND race_entry_id IS NULL)",
            name="steward_entry_link_status",
        ),
        sa.CheckConstraint(
            "first_observed_at_ms > 0 AND last_observed_at_ms >= first_observed_at_ms "
            "AND ingested_at_ms >= last_observed_at_ms", name="steward_observation_times",
        ),
        sa.CheckConstraint(
            "(NOT historical_publication_time_verified AND source_published_at_ms IS NULL) OR "
            "(historical_publication_time_verified AND source_published_at_ms IS NOT NULL "
            "AND source_published_at_ms > 0 AND source_published_at_ms <= first_observed_at_ms)",
            name="steward_publication_evidence",
        ),
    )
    op.create_index("ix_horse_steward_phrases_race", "horse_steward_phrases", ["race_id"])
    op.create_index("ix_horse_steward_phrases_entry", "horse_steward_phrases", ["race_entry_id"])
    op.create_index("ix_horse_steward_phrases_report", "horse_steward_phrases", ["race_steward_report_id"])
    op.create_index("ix_horse_steward_phrases_observed", "horse_steward_phrases", ["first_observed_at_ms"])


def downgrade():
    op.drop_table("horse_steward_phrases")
