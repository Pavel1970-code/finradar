"""Add trusted keys, package replay protection, and immutable import audit."""

from alembic import op
import sqlalchemy as sa


revision = "0004_regulatory_security"
down_revision = "0003_fiscal_registry"
branch_labels = None
depends_on = None


IMMUTABLE_TABLES = (
    "regulatory_trusted_keys",
    "regulatory_trusted_key_events",
    "regulatory_package_imports",
    "regulatory_accepted_packages",
)


def upgrade() -> None:
    op.create_table(
        "regulatory_trusted_keys",
        sa.Column("key_id", sa.String(length=36), nullable=False),
        sa.Column("algorithm", sa.String(length=20), nullable=False),
        sa.Column("public_key_base64", sa.String(length=44), nullable=False),
        sa.Column("public_key_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key_id"),
        sa.UniqueConstraint("public_key_fingerprint"),
    )
    op.create_index(
        op.f("ix_regulatory_trusted_keys_public_key_fingerprint"),
        "regulatory_trusted_keys",
        ["public_key_fingerprint"],
    )
    op.create_table(
        "regulatory_trusted_key_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("key_id", sa.String(length=36), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["key_id"], ["regulatory_trusted_keys.key_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "key_id", "sequence", name="uq_regulatory_key_event_sequence"
        ),
    )
    op.create_index(
        op.f("ix_regulatory_trusted_key_events_key_id"),
        "regulatory_trusted_key_events",
        ["key_id"],
    )
    op.create_table(
        "regulatory_package_imports",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("package_id", sa.String(length=36), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("original_name", sa.String(length=255), nullable=False),
        sa.Column("archive_location", sa.String(length=500), nullable=False),
        sa.Column("signing_key_id", sa.String(length=36), nullable=True),
        sa.Column("outcome", sa.String(length=30), nullable=False),
        sa.Column("reason_code", sa.String(length=60), nullable=False),
        sa.Column("reason_detail", sa.String(length=500), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("package_id", "content_hash", "signing_key_id", "outcome"):
        op.create_index(
            op.f(f"ix_regulatory_package_imports_{column}"),
            "regulatory_package_imports",
            [column],
        )
    op.create_table(
        "regulatory_accepted_packages",
        sa.Column("package_id", sa.String(length=36), nullable=False),
        sa.Column("import_id", sa.String(length=36), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("signing_key_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["import_id"], ["regulatory_package_imports.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["signing_key_id"], ["regulatory_trusted_keys.key_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("package_id"),
        sa.UniqueConstraint("import_id"),
    )
    op.create_index(
        op.f("ix_regulatory_accepted_packages_signing_key_id"),
        "regulatory_accepted_packages",
        ["signing_key_id"],
    )

    for table in IMMUTABLE_TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_no_update BEFORE UPDATE ON {table} BEGIN "
            f"SELECT RAISE(ABORT, '{table} is immutable'); END"
        )
        op.execute(
            f"CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table} BEGIN "
            f"SELECT RAISE(ABORT, '{table} is immutable'); END"
        )


def downgrade() -> None:
    for table in reversed(IMMUTABLE_TABLES):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_delete")
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_update")
    op.drop_index(
        op.f("ix_regulatory_accepted_packages_signing_key_id"),
        table_name="regulatory_accepted_packages",
    )
    op.drop_table("regulatory_accepted_packages")
    for column in ("outcome", "signing_key_id", "content_hash", "package_id"):
        op.drop_index(
            op.f(f"ix_regulatory_package_imports_{column}"),
            table_name="regulatory_package_imports",
        )
    op.drop_table("regulatory_package_imports")
    op.drop_index(
        op.f("ix_regulatory_trusted_key_events_key_id"),
        table_name="regulatory_trusted_key_events",
    )
    op.drop_table("regulatory_trusted_key_events")
    op.drop_index(
        op.f("ix_regulatory_trusted_keys_public_key_fingerprint"),
        table_name="regulatory_trusted_keys",
    )
    op.drop_table("regulatory_trusted_keys")
