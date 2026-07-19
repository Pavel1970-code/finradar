"""Allow audit records for rejected packages that were never safely read."""

from alembic import op
import sqlalchemy as sa


revision = "0005_regulatory_preflight"
down_revision = "0004_regulatory_security"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _drop_immutability_triggers()
    with op.batch_alter_table("regulatory_package_imports") as batch_op:
        batch_op.alter_column(
            "content_hash",
            existing_type=sa.String(length=64),
            nullable=True,
        )
        batch_op.alter_column(
            "archive_location",
            existing_type=sa.String(length=500),
            nullable=True,
        )
    _create_immutability_triggers()


def downgrade() -> None:
    connection = op.get_bind()
    missing_values = connection.execute(
        sa.text(
            "SELECT COUNT(*) FROM regulatory_package_imports "
            "WHERE content_hash IS NULL OR archive_location IS NULL"
        )
    ).scalar_one()
    if missing_values:
        raise RuntimeError(
            "Cannot downgrade regulatory audit while preflight-only records exist."
        )
    _drop_immutability_triggers()
    with op.batch_alter_table("regulatory_package_imports") as batch_op:
        batch_op.alter_column(
            "archive_location",
            existing_type=sa.String(length=500),
            nullable=False,
        )
        batch_op.alter_column(
            "content_hash",
            existing_type=sa.String(length=64),
            nullable=False,
        )
    _create_immutability_triggers()


def _drop_immutability_triggers() -> None:
    op.execute("DROP TRIGGER IF EXISTS regulatory_package_imports_no_delete")
    op.execute("DROP TRIGGER IF EXISTS regulatory_package_imports_no_update")


def _create_immutability_triggers() -> None:
    op.execute(
        "CREATE TRIGGER regulatory_package_imports_no_update "
        "BEFORE UPDATE ON regulatory_package_imports BEGIN "
        "SELECT RAISE(ABORT, 'regulatory_package_imports is immutable'); END"
    )
    op.execute(
        "CREATE TRIGGER regulatory_package_imports_no_delete "
        "BEFORE DELETE ON regulatory_package_imports BEGIN "
        "SELECT RAISE(ABORT, 'regulatory_package_imports is immutable'); END"
    )
