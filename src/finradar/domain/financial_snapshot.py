from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from finradar.domain.payroll import PayrollRecord


class DatasetKind(str, Enum):
    COMPANY_PROFILE = "company_profile"
    ACCOUNT_BALANCES = "account_balances"
    ACCOUNTING_FACTS = "accounting_facts"
    PAYMENT_CALENDAR = "payment_calendar"
    BANK_TRANSACTIONS = "bank_transactions"
    PAYROLL = "payroll"


class SourceIssueSeverity(str, Enum):
    WARNING = "warning"
    ERROR = "error"


class FinancialEventKind(str, Enum):
    FACT = "fact"
    PLANNED = "planned"


class FinancialDirection(str, Enum):
    INFLOW = "inflow"
    OUTFLOW = "outflow"


class FinancialEventStatus(str, Enum):
    PLANNED = "planned"
    CONFIRMED = "confirmed"
    SETTLED = "settled"
    CANCELLED = "cancelled"


class CounterpartyKind(str, Enum):
    CUSTOMER = "customer"
    SUPPLIER = "supplier"
    LANDLORD = "landlord"
    EMPLOYEES = "employees"
    TAX_AUTHORITY = "tax_authority"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class CompanyProfile:
    external_id: str
    name: str
    base_currency: str
    jurisdiction: str | None = None
    tax_regime: str | None = None


@dataclass(frozen=True, slots=True)
class AccountBalance:
    external_id: str
    name: str
    currency: str
    amount: Decimal
    balance_date: date


@dataclass(frozen=True, slots=True)
class AccountingMetric:
    code: str
    amount: Decimal
    currency: str
    period_start: date
    period_end: date
    source_reference: str = ""


@dataclass(frozen=True, slots=True)
class SourceDataIssue:
    code: str
    severity: SourceIssueSeverity
    dataset: DatasetKind
    message: str
    impact: str
    source_reference: str = ""


@dataclass(frozen=True, slots=True)
class IntegrationReference:
    connector_kind: str
    source_system: str
    synchronization_run_id: str
    cursor: str | None = None


@dataclass(frozen=True, slots=True)
class CounterpartyReference:
    external_id: str
    name: str
    kind: CounterpartyKind


@dataclass(frozen=True, slots=True)
class PaymentBasis:
    document_type: str
    document_number: str
    document_date: date
    description: str = ""


@dataclass(frozen=True, slots=True)
class FinancialEvent:
    external_id: str
    title: str
    amount: Decimal
    currency: str
    due_date: date
    direction: FinancialDirection
    kind: FinancialEventKind
    status: FinancialEventStatus = FinancialEventStatus.PLANNED
    settled_amount: Decimal = Decimal("0.00")
    obligation_key: str | None = None
    related_obligation_key: str | None = None
    fiscal_consequence_type: str | None = None
    category: str | None = None
    account_external_id: str | None = None
    source_reference: str = ""
    bank_transaction_id: str | None = None
    counterparty: CounterpartyReference | None = None
    payment_purpose: str = ""
    payment_basis: PaymentBasis | None = None
    period_start: date | None = None
    period_end: date | None = None


@dataclass(frozen=True, slots=True)
class FinancialSnapshot:
    source_system: str
    captured_at: datetime
    available_datasets: frozenset[DatasetKind]
    company: CompanyProfile | None
    balances: tuple[AccountBalance, ...] = ()
    metrics: tuple[AccountingMetric, ...] = ()
    events: tuple[FinancialEvent, ...] = ()
    payroll_records: tuple[PayrollRecord, ...] = ()
    source_issues: tuple[SourceDataIssue, ...] = ()
    source_cursor: str | None = None
    integration_references: tuple[IntegrationReference, ...] = ()

    def supplies(self, dataset: DatasetKind) -> bool:
        return dataset in self.available_datasets
