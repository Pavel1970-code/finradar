"""Add immutable fiscal rule registry and analysis history."""

from alembic import op
import sqlalchemy as sa


revision = "0003_fiscal_registry"
down_revision = "0002_sync_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fiscal_rule_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("rule_id", sa.String(length=120), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("rule_type", sa.String(length=40), nullable=False),
        sa.Column("content_json", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("source_reference", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rule_id", "version", name="uq_fiscal_rule_version"),
    )
    op.create_index(
        op.f("ix_fiscal_rule_versions_rule_id"),
        "fiscal_rule_versions",
        ["rule_id"],
    )
    op.create_index(
        op.f("ix_fiscal_rule_versions_content_hash"),
        "fiscal_rule_versions",
        ["content_hash"],
    )
    op.create_table(
        "fiscal_rule_lifecycle_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("rule_version_id", sa.String(length=36), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["rule_version_id"], ["fiscal_rule_versions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "rule_version_id", "sequence", name="uq_fiscal_rule_lifecycle_sequence"
        ),
    )
    op.create_index(
        op.f("ix_fiscal_rule_lifecycle_events_rule_version_id"),
        "fiscal_rule_lifecycle_events",
        ["rule_version_id"],
    )
    op.create_table(
        "fiscal_analysis_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("synchronization_run_id", sa.String(length=36), nullable=True),
        sa.Column("analysis_date", sa.Date(), nullable=False),
        sa.Column("horizon_days", sa.Integer(), nullable=False),
        sa.Column("algorithm_version", sa.String(length=40), nullable=False),
        sa.Column("rule_result_count", sa.Integer(), nullable=False),
        sa.Column("consequence_count", sa.Integer(), nullable=False),
        sa.Column("content_json", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["synchronization_run_id"],
            ["synchronization_runs.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_fiscal_analysis_runs_analysis_date"),
        "fiscal_analysis_runs",
        ["analysis_date"],
    )
    op.create_index(
        op.f("ix_fiscal_analysis_runs_synchronization_run_id"),
        "fiscal_analysis_runs",
        ["synchronization_run_id"],
    )
    for table in (
        "fiscal_rule_versions",
        "fiscal_rule_lifecycle_events",
        "fiscal_analysis_runs",
    ):
        op.execute(
            f"CREATE TRIGGER {table}_no_update BEFORE UPDATE ON {table} BEGIN "
            f"SELECT RAISE(ABORT, '{table} is immutable'); END"
        )
        op.execute(
            f"CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table} BEGIN "
            f"SELECT RAISE(ABORT, '{table} is immutable'); END"
        )


def downgrade() -> None:
    for table in (
        "fiscal_analysis_runs",
        "fiscal_rule_lifecycle_events",
        "fiscal_rule_versions",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_delete")
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_update")
    op.drop_index(
        op.f("ix_fiscal_analysis_runs_synchronization_run_id"),
        table_name="fiscal_analysis_runs",
    )
    op.drop_index(
        op.f("ix_fiscal_analysis_runs_analysis_date"),
        table_name="fiscal_analysis_runs",
    )
    op.drop_table("fiscal_analysis_runs")
    op.drop_index(
        op.f("ix_fiscal_rule_lifecycle_events_rule_version_id"),
        table_name="fiscal_rule_lifecycle_events",
    )
    op.drop_table("fiscal_rule_lifecycle_events")
    op.drop_index(
        op.f("ix_fiscal_rule_versions_content_hash"),
        table_name="fiscal_rule_versions",
    )
    op.drop_index(
        op.f("ix_fiscal_rule_versions_rule_id"),
        table_name="fiscal_rule_versions",
    )
    op.drop_table("fiscal_rule_versions")

