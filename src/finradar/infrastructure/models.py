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
    UniqueConstraint,
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


class FiscalRuleVersion(Base):
    __tablename__ = "fiscal_rule_versions"
    __table_args__ = (UniqueConstraint("rule_id", "version", name="uq_fiscal_rule_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=create_id)
    rule_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    rule_type: Mapped[str] = mapped_column(String(40), nullable=False)
    content_json: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_reference: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    lifecycle_events: Mapped[list[FiscalRuleLifecycleEvent]] = relationship(
        back_populates="rule_version",
        cascade="save-update, merge",
        order_by="FiscalRuleLifecycleEvent.sequence",
    )


class FiscalRuleLifecycleEvent(Base):
    __tablename__ = "fiscal_rule_lifecycle_events"
    __table_args__ = (
        UniqueConstraint(
            "rule_version_id", "sequence", name="uq_fiscal_rule_lifecycle_sequence"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=create_id)
    rule_version_id: Mapped[str] = mapped_column(
        ForeignKey("fiscal_rule_versions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    rule_version: Mapped[FiscalRuleVersion] = relationship(
        back_populates="lifecycle_events"
    )


class FiscalAnalysisRun(Base):
    __tablename__ = "fiscal_analysis_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=create_id)
    synchronization_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("synchronization_runs.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    analysis_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    horizon_days: Mapped[int] = mapped_column(Integer, nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(40), nullable=False)
    rule_result_count: Mapped[int] = mapped_column(Integer, nullable=False)
    consequence_count: Mapped[int] = mapped_column(Integer, nullable=False)
    content_json: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class RegulatoryTrustedKey(Base):
    __tablename__ = "regulatory_trusted_keys"

    key_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    algorithm: Mapped[str] = mapped_column(String(20), nullable=False)
    public_key_base64: Mapped[str] = mapped_column(String(44), nullable=False)
    public_key_fingerprint: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    lifecycle_events: Mapped[list[RegulatoryTrustedKeyEvent]] = relationship(
        back_populates="trusted_key",
        cascade="save-update, merge",
        order_by="RegulatoryTrustedKeyEvent.sequence",
    )


class RegulatoryTrustedKeyEvent(Base):
    __tablename__ = "regulatory_trusted_key_events"
    __table_args__ = (
        UniqueConstraint("key_id", "sequence", name="uq_regulatory_key_event_sequence"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=create_id)
    key_id: Mapped[str] = mapped_column(
        ForeignKey("regulatory_trusted_keys.key_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    trusted_key: Mapped[RegulatoryTrustedKey] = relationship(
        back_populates="lifecycle_events"
    )


class RegulatoryTrustBootstrap(Base):
    __tablename__ = "regulatory_trust_bootstrap"

    singleton_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key_id: Mapped[str] = mapped_column(
        ForeignKey("regulatory_trusted_keys.key_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    record_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class RegulatoryKeyRotation(Base):
    __tablename__ = "regulatory_key_rotations"

    rotation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    previous_key_id: Mapped[str] = mapped_column(
        ForeignKey("regulatory_trusted_keys.key_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    new_key_id: Mapped[str] = mapped_column(
        ForeignKey("regulatory_trusted_keys.key_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class RegulatoryPackageImport(Base):
    __tablename__ = "regulatory_package_imports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=create_id)
    package_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    archive_location: Mapped[str | None] = mapped_column(String(500), nullable=True)
    signing_key_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    outcome: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    reason_code: Mapped[str] = mapped_column(String(60), nullable=False)
    reason_detail: Mapped[str] = mapped_column(String(500), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class RegulatoryAcceptedPackage(Base):
    __tablename__ = "regulatory_accepted_packages"

    package_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    import_id: Mapped[str] = mapped_column(
        ForeignKey("regulatory_package_imports.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    signing_key_id: Mapped[str] = mapped_column(
        ForeignKey("regulatory_trusted_keys.key_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class RegulatoryArchiveEvent(Base):
    __tablename__ = "regulatory_archive_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=create_id)
    import_id: Mapped[str] = mapped_column(
        ForeignKey("regulatory_package_imports.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class BankSynchronizationRun(Base):
    __tablename__ = "bank_synchronization_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=create_id)
    source_system: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    available: Mapped[int] = mapped_column(Integer, nullable=False)
    statement_count: Mapped[int] = mapped_column(Integer, nullable=False)
    transaction_count: Mapped[int] = mapped_column(Integer, nullable=False)
    issue_count: Mapped[int] = mapped_column(Integer, nullable=False)
    next_cursor: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    snapshot: Mapped[BankStatementSnapshot] = relationship(
        back_populates="run",
        uselist=False,
        cascade="save-update, merge",
    )


class BankStatementSnapshot(Base):
    __tablename__ = "bank_statement_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=create_id)
    bank_synchronization_run_id: Mapped[str] = mapped_column(
        ForeignKey("bank_synchronization_runs.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    content_json: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    run: Mapped[BankSynchronizationRun] = relationship(back_populates="snapshot")


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
