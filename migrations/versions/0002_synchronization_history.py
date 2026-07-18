"""Add synchronization runs and immutable source snapshots."""

from alembic import op
import sqlalchemy as sa


revision = "0002_sync_history"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "synchronization_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source_system", sa.String(length=100), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("readiness_status", sa.String(length=20), nullable=False),
        sa.Column("issue_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_synchronization_runs_captured_at"),
        "synchronization_runs",
        ["captured_at"],
    )
    op.create_index(
        op.f("ix_synchronization_runs_source_system"),
        "synchronization_runs",
        ["source_system"],
    )
    op.create_table(
        "source_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("synchronization_run_id", sa.String(length=36), nullable=False),
        sa.Column("content_json", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["synchronization_run_id"],
            ["synchronization_runs.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("synchronization_run_id"),
    )
    op.create_index(
        op.f("ix_source_snapshots_content_hash"), "source_snapshots", ["content_hash"]
    )
    op.execute(
        "CREATE TRIGGER source_snapshots_no_update "
        "BEFORE UPDATE ON source_snapshots BEGIN "
        "SELECT RAISE(ABORT, 'source snapshots are immutable'); END"
    )
    op.execute(
        "CREATE TRIGGER source_snapshots_no_delete "
        "BEFORE DELETE ON source_snapshots BEGIN "
        "SELECT RAISE(ABORT, 'source snapshots are immutable'); END"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS source_snapshots_no_delete")
    op.execute("DROP TRIGGER IF EXISTS source_snapshots_no_update")
    op.drop_index(op.f("ix_source_snapshots_content_hash"), table_name="source_snapshots")
    op.drop_table("source_snapshots")
    op.drop_index(
        op.f("ix_synchronization_runs_source_system"),
        table_name="synchronization_runs",
    )
    op.drop_index(
        op.f("ix_synchronization_runs_captured_at"),
        table_name="synchronization_runs",
    )
    op.drop_table("synchronization_runs")

