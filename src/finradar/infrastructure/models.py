from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from uuid import uuid4

from sqlalchemy import (
    Date,
    DateTime,
    Enum as SqlEnum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from finradar.infrastructure.database import Base


def create_id() -> str:
    return str(uuid4())


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class FlowDirection(str, Enum):
    INFLOW = "inflow"
    OUTFLOW = "outflow"


class FlowStatus(str, Enum):
    PLANNED = "planned"
    CONFIRMED = "confirmed"
    SETTLED = "settled"
    CANCELLED = "cancelled"


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=create_id,
    )
    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )
    base_currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="GEL",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )

    accounts: Mapped[list[CashAccount]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
    )
    cash_flow_items: Mapped[list[CashFlowItem]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
    )


class SynchronizationRun(Base):
    __tablename__ = "synchronization_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=create_id)
    source_system: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    readiness_status: Mapped[str] = mapped_column(String(20), nullable=False)
    issue_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    snapshot: Mapped[SourceSnapshot] = relationship(
        back_populates="run",
        uselist=False,
        cascade="save-update, merge",
    )


class SourceSnapshot(Base):
    __tablename__ = "source_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=create_id)
    synchronization_run_id: Mapped[str] = mapped_column(
        ForeignKey("synchronization_runs.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    content_json: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    run: Mapped[SynchronizationRun] = relationship(back_populates="snapshot")


class CashAccount(Base):
    __tablename__ = "cash_accounts"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=create_id,
    )
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="GEL",
    )
    current_balance: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        default=Decimal("0.00"),
    )
    balance_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )

    company: Mapped[Company] = relationship(
        back_populates="accounts",
    )
    cash_flow_items: Mapped[list[CashFlowItem]] = relationship(
        back_populates="account",
    )


class CashFlowItem(Base):
    __tablename__ = "cash_flow_items"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=create_id,
    )
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    account_id: Mapped[str | None] = mapped_column(
        ForeignKey("cash_accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )
    category: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    direction: Mapped[FlowDirection] = mapped_column(
        SqlEnum(
            FlowDirection,
            name="flow_direction",
            native_enum=False,
        ),
        nullable=False,
    )
    status: Mapped[FlowStatus] = mapped_column(
        SqlEnum(
            FlowStatus,
            name="flow_status",
            native_enum=False,
        ),
        nullable=False,
        default=FlowStatus.PLANNED,
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
    )
    due_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        index=True,
    )
    source: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="manual",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )

    company: Mapped[Company] = relationship(
        back_populates="cash_flow_items",
    )
    account: Mapped[CashAccount | None] = relationship(
        back_populates="cash_flow_items",
    )
