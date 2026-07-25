"""Add immutable company tax-profile versions."""

from alembic import op
import sqlalchemy as sa


revision = "0008_tax_profile"
down_revision = "0007_integration_sdk"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tax_profile_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_external_id", sa.String(length=200), nullable=False),
        sa.Column("profile_version", sa.Integer(), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("questionnaire_version", sa.Integer(), nullable=False),
        sa.Column("content_json", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "profile_version >= 1",
            name="ck_tax_profile_version_positive",
        ),
        sa.CheckConstraint(
            "questionnaire_version >= 1",
            name="ck_tax_profile_questionnaire_version_positive",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "company_external_id",
            "profile_version",
            name="uq_tax_profile_company_version",
        ),
    )
    op.create_index(
        op.f("ix_tax_profile_versions_company_external_id"),
        "tax_profile_versions",
        ["company_external_id"],
    )
    op.create_index(
        op.f("ix_tax_profile_versions_valid_from"),
        "tax_profile_versions",
        ["valid_from"],
    )
    op.create_index(
        op.f("ix_tax_profile_versions_content_hash"),
        "tax_profile_versions",
        ["content_hash"],
    )
    op.execute(
        "CREATE TRIGGER tax_profile_versions_no_update "
        "BEFORE UPDATE ON tax_profile_versions BEGIN "
        "SELECT RAISE(ABORT, 'tax_profile_versions is immutable'); END"
    )
    op.execute(
        "CREATE TRIGGER tax_profile_versions_no_delete "
        "BEFORE DELETE ON tax_profile_versions BEGIN "
        "SELECT RAISE(ABORT, 'tax_profile_versions is immutable'); END"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS tax_profile_versions_no_delete")
    op.execute("DROP TRIGGER IF EXISTS tax_profile_versions_no_update")
    op.drop_index(
        op.f("ix_tax_profile_versions_content_hash"),
        table_name="tax_profile_versions",
    )
    op.drop_index(
        op.f("ix_tax_profile_versions_valid_from"),
        table_name="tax_profile_versions",
    )
    op.drop_index(
        op.f("ix_tax_profile_versions_company_external_id"),
        table_name="tax_profile_versions",
    )
    op.drop_table("tax_profile_versions")
