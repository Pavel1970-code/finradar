"""Add immutable local bank synchronization history."""

from alembic import op
import sqlalchemy as sa


revision = "0007_integration_sdk"
down_revision = "0006_trust_bootstrap"
branch_labels = None
depends_on = None


TABLES = ("bank_synchronization_runs", "bank_statement_snapshots")


def upgrade() -> None:
    op.create_table(
        "bank_synchronization_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source_system", sa.String(length=100), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available", sa.Integer(), nullable=False),
        sa.Column("statement_count", sa.Integer(), nullable=False),
        sa.Column("transaction_count", sa.Integer(), nullable=False),
        sa.Column("issue_count", sa.Integer(), nullable=False),
        sa.Column("next_cursor", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("available IN (0, 1)", name="ck_bank_sync_available"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_bank_synchronization_runs_source_system"),
        "bank_synchronization_runs",
        ["source_system"],
    )
    op.create_index(
        op.f("ix_bank_synchronization_runs_captured_at"),
        "bank_synchronization_runs",
        ["captured_at"],
    )
    op.create_table(
        "bank_statement_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("bank_synchronization_run_id", sa.String(length=36), nullable=False),
        sa.Column("content_json", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["bank_synchronization_run_id"],
            ["bank_synchronization_runs.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bank_synchronization_run_id"),
    )
    op.create_index(
        op.f("ix_bank_statement_snapshots_content_hash"),
        "bank_statement_snapshots",
        ["content_hash"],
    )
    for table in TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_no_update BEFORE UPDATE ON {table} BEGIN "
            f"SELECT RAISE(ABORT, '{table} is immutable'); END"
        )
        op.execute(
            f"CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table} BEGIN "
            f"SELECT RAISE(ABORT, '{table} is immutable'); END"
        )


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_delete")
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_update")
    op.drop_index(
        op.f("ix_bank_statement_snapshots_content_hash"),
        table_name="bank_statement_snapshots",
    )
    op.drop_table("bank_statement_snapshots")
    op.drop_index(
        op.f("ix_bank_synchronization_runs_captured_at"),
        table_name="bank_synchronization_runs",
    )
    op.drop_index(
        op.f("ix_bank_synchronization_runs_source_system"),
        table_name="bank_synchronization_runs",
    )
    op.drop_table("bank_synchronization_runs")
