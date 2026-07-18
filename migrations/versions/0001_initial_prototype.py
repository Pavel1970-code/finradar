"""Create the initial prototype schema."""

from alembic import op
import sqlalchemy as sa


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "companies",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("base_currency", sa.String(length=3), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "cash_accounts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("current_balance", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("balance_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_cash_accounts_company_id"), "cash_accounts", ["company_id"]
    )
    op.create_table(
        "cash_flow_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("account_id", sa.String(length=36), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column(
            "direction",
            sa.Enum("INFLOW", "OUTFLOW", name="flow_direction", native_enum=False),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "PLANNED",
                "CONFIRMED",
                "SETTLED",
                "CANCELLED",
                name="flow_status",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["cash_accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_cash_flow_items_account_id"), "cash_flow_items", ["account_id"]
    )
    op.create_index(
        op.f("ix_cash_flow_items_company_id"), "cash_flow_items", ["company_id"]
    )
    op.create_index(op.f("ix_cash_flow_items_due_date"), "cash_flow_items", ["due_date"])


def downgrade() -> None:
    op.drop_index(op.f("ix_cash_flow_items_due_date"), table_name="cash_flow_items")
    op.drop_index(op.f("ix_cash_flow_items_company_id"), table_name="cash_flow_items")
    op.drop_index(op.f("ix_cash_flow_items_account_id"), table_name="cash_flow_items")
    op.drop_table("cash_flow_items")
    op.drop_index(op.f("ix_cash_accounts_company_id"), table_name="cash_accounts")
    op.drop_table("cash_accounts")
    op.drop_table("companies")

