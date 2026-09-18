"""Persist reproducible runner predictions, model components, and explanations."""

import sqlalchemy as sa
from alembic import op

revision = "20260919_0013"
down_revision = "20260918_0012"
branch_labels = None
depends_on = None


def _install_immutable_triggers(table_name: str) -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            sa.text(
                f"""
                CREATE TRIGGER trg_{table_name}_immutable
                BEFORE UPDATE OR DELETE ON {table_name}
                FOR EACH ROW EXECUTE FUNCTION prevent_prediction_ledger_mutation()
                """
            )
        )
    elif bind.dialect.name == "sqlite":
        for action in ("UPDATE", "DELETE"):
            op.execute(
                sa.text(
                    f"""
                    CREATE TRIGGER trg_{table_name}_no_{action.lower()}
                    BEFORE {action} ON {table_name}
                    BEGIN
                        SELECT RAISE(ABORT, 'immutable prediction ledger');
                    END
                    """
                )
            )


def upgrade() -> None:
    prediction_run_columns = (
        sa.Column("publication_content_sha256", sa.String(length=64), nullable=True),
        sa.Column("domain", sa.String(length=20), nullable=True),
        sa.Column("prediction_stage", sa.String(length=30), nullable=True),
        sa.Column("parent_prediction_run_id", sa.Integer(), nullable=True),
        sa.Column("registry_sha256", sa.String(length=64), nullable=True),
        sa.Column("input_card_sha256", sa.String(length=64), nullable=True),
        sa.Column("source_card_at_ms", sa.BigInteger(), nullable=True),
        sa.Column("history_cutoff_date", sa.Date(), nullable=True),
        sa.Column("data_availability_status", sa.String(length=30), nullable=True),
        sa.Column("probability_contract", sa.String(length=100), nullable=True),
        sa.Column("combination_algorithm_version", sa.String(length=100), nullable=True),
    )
    for column in prediction_run_columns:
        op.add_column("prediction_runs", column)
    op.create_unique_constraint(
        "uq_prediction_runs_publication_content_sha256",
        "prediction_runs",
        ["publication_content_sha256"],
    ) if op.get_bind().dialect.name == "postgresql" else None
    op.create_index(
        "ix_prediction_runs_parent_id",
        "prediction_runs",
        ["parent_prediction_run_id"],
    )

    prediction_columns = (
        sa.Column("a_rank_in_race", sa.Integer(), nullable=True),
        sa.Column("field_size", sa.Integer(), nullable=True),
        sa.Column("raw_a_top3_score", sa.Float(), nullable=True),
        sa.Column("raw_bc_top3_score", sa.Float(), nullable=True),
        sa.Column("raw_win_score", sa.Float(), nullable=True),
        sa.Column("raw_rank_score", sa.Float(), nullable=True),
        sa.Column("raw_order_score", sa.Float(), nullable=True),
        sa.Column("beta_set", sa.Float(), nullable=True),
        sa.Column("beta_order", sa.Float(), nullable=True),
        sa.Column("runner_identifier", sa.String(length=50), nullable=True),
        sa.Column("jockey_identifier", sa.String(length=50), nullable=True),
        sa.Column("trainer_identifier", sa.String(length=50), nullable=True),
        sa.Column("owner_identifier", sa.String(length=50), nullable=True),
        sa.Column("starter_status", sa.String(length=30), nullable=True),
        sa.Column("cancellation_status", sa.String(length=30), nullable=True),
        sa.Column("body_weight_kg", sa.Float(), nullable=True),
        sa.Column("body_weight_change_kg", sa.Float(), nullable=True),
        sa.Column("data_quality_flags_json", sa.Text(), nullable=True),
    )
    for column in prediction_columns:
        op.add_column("model_predictions", column)

    if op.get_bind().dialect.name == "postgresql":
        op.create_foreign_key(
            "fk_prediction_runs_parent_prediction_run_id_prediction_runs",
            "prediction_runs",
            "prediction_runs",
            ["parent_prediction_run_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        op.create_check_constraint(
            "ck_prediction_runs_domain",
            "prediction_runs",
            "domain IS NULL OR domain IN ('thoroughbred', 'jeju')",
        )
        op.create_check_constraint(
            "ck_prediction_runs_stage",
            "prediction_runs",
            "prediction_stage IS NULL OR prediction_stage IN "
            "('initial_card', 'pre_race_update')",
        )
        op.create_check_constraint(
            "ck_prediction_runs_availability",
            "prediction_runs",
            "data_availability_status IS NULL OR data_availability_status IN "
            "('complete', 'partial', 'not_available')",
        )
        op.create_check_constraint(
            "ck_model_predictions_positive_rank",
            "model_predictions",
            "a_rank_in_race IS NULL OR a_rank_in_race > 0",
        )
        op.create_check_constraint(
            "ck_model_predictions_positive_field_size",
            "model_predictions",
            "field_size IS NULL OR field_size > 0",
        )

    op.create_table(
        "prediction_model_components",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("prediction_run_id", sa.Integer(), nullable=False),
        sa.Column("component", sa.String(length=30), nullable=False),
        sa.Column("model_version", sa.String(length=150), nullable=False),
        sa.Column("candidate_name", sa.String(length=100), nullable=False),
        sa.Column("artifact_sha256", sa.String(length=64), nullable=False),
        sa.Column("metadata_sha256", sa.String(length=64), nullable=True),
        sa.Column("algorithm_version", sa.String(length=100), nullable=True),
        sa.Column("parameters_json", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["prediction_run_id"],
            ["prediction_runs.id"],
            name="fk_prediction_model_components_prediction_run_id_prediction_runs",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_prediction_model_components"),
        sa.UniqueConstraint(
            "prediction_run_id",
            "component",
            name="uq_prediction_model_components_run_component",
        ),
    )
    op.create_index(
        "ix_prediction_model_components_run_id",
        "prediction_model_components",
        ["prediction_run_id"],
    )

    op.create_table(
        "model_prediction_explanations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("model_prediction_id", sa.Integer(), nullable=False),
        sa.Column("component", sa.String(length=30), nullable=False),
        sa.Column("feature_name", sa.String(length=150), nullable=False),
        sa.Column("readable_feature_name", sa.String(length=150), nullable=False),
        sa.Column("feature_value_json", sa.Text(), nullable=False),
        sa.Column("field_percentile", sa.Float(), nullable=True),
        sa.Column("contribution_direction", sa.String(length=10), nullable=False),
        sa.Column("contribution_value", sa.Float(), nullable=False),
        sa.Column("contribution_rank", sa.Integer(), nullable=False),
        sa.Column("explanation_type", sa.String(length=30), nullable=False),
        sa.Column("explanation_method", sa.String(length=50), nullable=False),
        sa.Column("source_cutoff_at_ms", sa.BigInteger(), nullable=True),
        sa.CheckConstraint(
            "contribution_direction IN ('positive', 'negative')",
            name="ck_model_prediction_explanations_direction",
        ),
        sa.CheckConstraint(
            "contribution_rank >= 1 AND contribution_rank <= 3",
            name="ck_model_prediction_explanations_rank",
        ),
        sa.CheckConstraint(
            "explanation_type IN "
            "('interpretable', 'categorical_model_effect', 'data_quality_flag')",
            name="ck_model_prediction_explanations_type",
        ),
        sa.CheckConstraint(
            "field_percentile IS NULL OR "
            "(field_percentile >= 0 AND field_percentile <= 1)",
            name="ck_model_prediction_explanations_percentile",
        ),
        sa.ForeignKeyConstraint(
            ["model_prediction_id"],
            ["model_predictions.id"],
            name="fk_model_prediction_explanations_model_prediction_id_model_predictions",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_model_prediction_explanations"),
        sa.UniqueConstraint(
            "model_prediction_id",
            "component",
            "contribution_direction",
            "contribution_rank",
            name="uq_model_prediction_explanations_direction_rank",
        ),
    )
    op.create_index(
        "ix_model_prediction_explanations_prediction_id",
        "model_prediction_explanations",
        ["model_prediction_id"],
    )

    for table_name in (
        "prediction_model_components",
        "model_prediction_explanations",
    ):
        _install_immutable_triggers(table_name)


def downgrade() -> None:
    op.drop_index(
        "ix_model_prediction_explanations_prediction_id",
        table_name="model_prediction_explanations",
    )
    op.drop_table("model_prediction_explanations")
    op.drop_index(
        "ix_prediction_model_components_run_id",
        table_name="prediction_model_components",
    )
    op.drop_table("prediction_model_components")

    for column in (
        "data_quality_flags_json",
        "body_weight_change_kg",
        "body_weight_kg",
        "cancellation_status",
        "starter_status",
        "owner_identifier",
        "trainer_identifier",
        "jockey_identifier",
        "runner_identifier",
        "beta_order",
        "beta_set",
        "raw_order_score",
        "raw_rank_score",
        "raw_win_score",
        "raw_bc_top3_score",
        "raw_a_top3_score",
        "field_size",
        "a_rank_in_race",
    ):
        op.drop_column("model_predictions", column)

    op.drop_index("ix_prediction_runs_parent_id", table_name="prediction_runs")
    for column in (
        "combination_algorithm_version",
        "probability_contract",
        "data_availability_status",
        "history_cutoff_date",
        "source_card_at_ms",
        "input_card_sha256",
        "registry_sha256",
        "parent_prediction_run_id",
        "prediction_stage",
        "domain",
        "publication_content_sha256",
    ):
        op.drop_column("prediction_runs", column)
