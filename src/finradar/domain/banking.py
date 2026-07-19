from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from finradar.domain.financial_snapshot import SourceDataIssue


class BankTransactionStatus(str, Enum):
    BOOKED = "booked"
    PENDING = "pending"
    REVERSED = "reversed"


class BankTransactionDirection(str, Enum):
    CREDIT = "credit"
    DEBIT = "debit"


@dataclass(frozen=True, slots=True)
class BankTransaction:
    external_id: str
    account_external_id: str
    booking_date: date
    value_date: date
    direction: BankTransactionDirection
    amount: Decimal
    currency: str
    description: str
    reference: str = ""
    status: BankTransactionStatus = BankTransactionStatus.BOOKED
    counterparty_name: str = ""
    counterparty_account: str = ""
    source_reference: str = ""

    def __post_init__(self) -> None:
        if not self.external_id.strip() or len(self.external_id) > 200:
            raise ValueError("Bank transaction identifier is invalid.")
        if not self.account_external_id.strip() or len(self.account_external_id) > 200:
            raise ValueError("Bank account identifier is invalid.")
        if not self.amount.is_finite() or self.amount <= Decimal("0"):
            raise ValueError("Bank transaction amount must be positive and finite.")
        if len(self.currency) != 3 or self.currency != self.currency.upper():
            raise ValueError("Bank transaction currency must be an uppercase ISO code.")
        if (self.booking_date - self.value_date).days > 31:
            raise ValueError("Bank value date is implausibly earlier than booking date.")


@dataclass(frozen=True, slots=True)
class BankStatement:
    statement_id: str
    account_external_id: str
    period_start: date
    period_end: date
    opening_balance: Decimal | None
    closing_balance: Decimal | None
    transactions: tuple[BankTransaction, ...]

    def __post_init__(self) -> None:
        if not self.statement_id.strip() or len(self.statement_id) > 200:
            raise ValueError("Bank statement identifier is invalid.")
        if self.period_end < self.period_start:
            raise ValueError("Bank statement period is invalid.")
        for balance in (self.opening_balance, self.closing_balance):
            if balance is not None and not balance.is_finite():
                raise ValueError("Bank statement balance must be finite.")
        if any(
            transaction.account_external_id != self.account_external_id
            for transaction in self.transactions
        ):
            raise ValueError("Bank statement contains a transaction for another account.")
        if any(
            not self.period_start <= transaction.booking_date <= self.period_end
            for transaction in self.transactions
        ):
            raise ValueError("Bank statement contains a transaction outside its period.")


@dataclass(frozen=True, slots=True)
class BankSynchronizationBatch:
    source_system: str
    captured_at: datetime
    available: bool
    statements: tuple[BankStatement, ...] = ()
    source_issues: tuple[SourceDataIssue, ...] = ()
    next_cursor: str | None = None

    @property
    def transactions(self) -> tuple[BankTransaction, ...]:
        return tuple(
            transaction
            for statement in self.statements
            for transaction in statement.transactions
        )

    @property
    def coverage_start(self) -> date | None:
        return min((item.period_start for item in self.statements), default=None)

    @property
    def coverage_end(self) -> date | None:
        return max((item.period_end for item in self.statements), default=None)
