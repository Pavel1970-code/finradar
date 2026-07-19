"""Lock initial trust, audit key rotations, and track archive retention."""

from alembic import op
import sqlalchemy as sa


revision = "0006_trust_bootstrap"
down_revision = "0005_regulatory_preflight"
branch_labels = None
depends_on = None


TABLES = (
    "regulatory_trust_bootstrap",
    "regulatory_key_rotations",
    "regulatory_archive_events",
)


def upgrade() -> None:
    op.create_table(
        "regulatory_trust_bootstrap",
        sa.Column("singleton_id", sa.Integer(), nullable=False),
        sa.Column("key_id", sa.String(length=36), nullable=False),
        sa.Column("record_hash", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("singleton_id = 1", name="ck_regulatory_bootstrap_singleton"),
        sa.ForeignKeyConstraint(
            ["key_id"], ["regulatory_trusted_keys.key_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("singleton_id"),
        sa.UniqueConstraint("key_id"),
    )
    op.create_table(
        "regulatory_key_rotations",
        sa.Column("rotation_id", sa.String(length=36), nullable=False),
        sa.Column("previous_key_id", sa.String(length=36), nullable=False),
        sa.Column("new_key_id", sa.String(length=36), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["previous_key_id"], ["regulatory_trusted_keys.key_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["new_key_id"], ["regulatory_trusted_keys.key_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("rotation_id"),
        sa.UniqueConstraint("new_key_id"),
    )
    op.create_index(
        op.f("ix_regulatory_key_rotations_previous_key_id"),
        "regulatory_key_rotations",
        ["previous_key_id"],
    )
    op.create_table(
        "regulatory_archive_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("import_id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["import_id"], ["regulatory_package_imports.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_regulatory_archive_events_import_id"),
        "regulatory_archive_events",
        ["import_id"],
    )
    op.create_index(
        op.f("ix_regulatory_archive_events_event_type"),
        "regulatory_archive_events",
        ["event_type"],
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
        op.f("ix_regulatory_archive_events_event_type"),
        table_name="regulatory_archive_events",
    )
    op.drop_index(
        op.f("ix_regulatory_archive_events_import_id"),
        table_name="regulatory_archive_events",
    )
    op.drop_table("regulatory_archive_events")
    op.drop_index(
        op.f("ix_regulatory_key_rotations_previous_key_id"),
        table_name="regulatory_key_rotations",
    )
    op.drop_table("regulatory_key_rotations")
    op.drop_table("regulatory_trust_bootstrap")
