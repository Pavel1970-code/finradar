from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum


class DatasetKind(str, Enum):
    COMPANY_PROFILE = "company_profile"
    ACCOUNT_BALANCES = "account_balances"
    ACCOUNTING_FACTS = "accounting_facts"
    PAYMENT_CALENDAR = "payment_calendar"


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
    category: str | None = None
    account_external_id: str | None = None


@dataclass(frozen=True, slots=True)
class FinancialSnapshot:
    source_system: str
    captured_at: datetime
    available_datasets: frozenset[DatasetKind]
    company: CompanyProfile | None
    balances: tuple[AccountBalance, ...] = ()
    metrics: tuple[AccountingMetric, ...] = ()
    events: tuple[FinancialEvent, ...] = ()

    def supplies(self, dataset: DatasetKind) -> bool:
        return dataset in self.available_datasets
