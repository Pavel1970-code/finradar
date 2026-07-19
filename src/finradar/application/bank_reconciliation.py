from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta
from enum import Enum

from finradar.domain.banking import (
    BankStatement,
    BankSynchronizationBatch,
    BankTransaction,
    BankTransactionDirection,
    BankTransactionStatus,
)
from finradar.domain.financial_snapshot import (
    DatasetKind,
    FinancialDirection,
    FinancialEvent,
    FinancialEventKind,
    FinancialEventStatus,
    FinancialSnapshot,
    IntegrationReference,
    SourceDataIssue,
    SourceIssueSeverity,
)


class BankMatchStatus(str, Enum):
    MATCHED = "matched"
    MISSING_IN_ACCOUNTING = "missing_in_accounting"
    AMBIGUOUS = "ambiguous"
    CONFLICT = "conflict"
    IGNORED = "ignored"


class BankMatchMethod(str, Enum):
    TRANSACTION_ID = "transaction_id"
    EXACT_FIELDS = "exact_fields"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class BankReconciliationItem:
    bank_transaction_id: str
    status: BankMatchStatus
    method: BankMatchMethod
    accounting_event_id: str | None = None


@dataclass(frozen=True, slots=True)
class BankReconciliationReport:
    source_system: str
    items: tuple[BankReconciliationItem, ...]
    source_issues: tuple[SourceDataIssue, ...]

    @property
    def matched_count(self) -> int:
        return sum(item.status is BankMatchStatus.MATCHED for item in self.items)

    @property
    def missing_count(self) -> int:
        return sum(
            item.status is BankMatchStatus.MISSING_IN_ACCOUNTING for item in self.items
        )


def reconcile_bank_batch(
    snapshot: FinancialSnapshot,
    batch: BankSynchronizationBatch,
    *,
    as_of: date,
    maximum_coverage_age_days: int = 1,
) -> BankReconciliationReport:
    if maximum_coverage_age_days < 0:
        raise ValueError("Maximum bank coverage age cannot be negative.")
    issues = list(batch.source_issues)
    if not batch.available:
        issues.append(
            _issue(
                "bank_transactions_unavailable",
                "Bank transactions are unavailable.",
                "Recent receipts and expenses cannot be reconciled with accounting.",
            )
        )
        return BankReconciliationReport(batch.source_system, (), tuple(issues))
    if not batch.statements:
        issues.append(
            _issue(
                "bank_statements_empty",
                "The bank source returned no statements.",
                "FinRadar cannot confirm recent cash movements.",
            )
        )
    elif batch.coverage_end is not None:
        oldest_allowed = as_of - timedelta(days=maximum_coverage_age_days)
        if batch.coverage_end < oldest_allowed:
            missing_days = (as_of - batch.coverage_end).days
            issues.append(
                _issue(
                    "bank_coverage_stale",
                    f"Банковская информация не охватывает последние {missing_days} дней.",
                    "В прогнозе могут отсутствовать недавние поступления или расходы.",
                )
            )

    for statement in batch.statements:
        issues.extend(_statement_issues(statement, snapshot))

    items = tuple(_match(transaction, snapshot.events) for transaction in batch.transactions)
    missing = sum(
        item.status is BankMatchStatus.MISSING_IN_ACCOUNTING for item in items
    )
    ambiguous = sum(item.status is BankMatchStatus.AMBIGUOUS for item in items)
    conflicts = sum(item.status is BankMatchStatus.CONFLICT for item in items)
    if missing:
        issues.append(
            _issue(
                "bank_transactions_missing_in_accounting",
                f"В бухгалтерских данных отсутствуют банковские операции: {missing}.",
                "Расходы или поступления могли быть не внесены бухгалтером.",
            )
        )
    if ambiguous:
        issues.append(
            _issue(
                "bank_reconciliation_ambiguous",
                f"Неоднозначные соответствия банковских операций: {ambiguous}.",
                "FinRadar не выбирает соответствие автоматически.",
            )
        )
    if conflicts:
        issues.append(
            _issue(
                "bank_reconciliation_conflict",
                f"Конфликтующие банковские и бухгалтерские записи: {conflicts}.",
                "Перед надёжным анализом необходимо исправить конфликтующие записи.",
            )
        )
    return BankReconciliationReport(batch.source_system, items, tuple(issues))


def attach_bank_reconciliation(
    snapshot: FinancialSnapshot,
    batch: BankSynchronizationBatch,
    report: BankReconciliationReport,
    *,
    synchronization_run_id: str | None = None,
) -> FinancialSnapshot:
    datasets = snapshot.available_datasets
    if batch.available:
        datasets = datasets | {DatasetKind.BANK_TRANSACTIONS}
    references = snapshot.integration_references
    if synchronization_run_id is not None:
        references += (
            IntegrationReference(
                connector_kind="bank",
                source_system=batch.source_system,
                synchronization_run_id=synchronization_run_id,
                cursor=batch.next_cursor,
            ),
        )
    return replace(
        snapshot,
        available_datasets=frozenset(datasets),
        source_issues=snapshot.source_issues + report.source_issues,
        integration_references=references,
    )


def _match(
    transaction: BankTransaction,
    events: tuple[FinancialEvent, ...],
) -> BankReconciliationItem:
    if transaction.status is not BankTransactionStatus.BOOKED:
        return BankReconciliationItem(
            bank_transaction_id=transaction.external_id,
            status=BankMatchStatus.IGNORED,
            method=BankMatchMethod.NONE,
        )
    exact_id = tuple(
        event for event in events if event.bank_transaction_id == transaction.external_id
    )
    if exact_id:
        if len(exact_id) == 1 and _same_values(transaction, exact_id[0]):
            return _matched(transaction, exact_id[0], BankMatchMethod.TRANSACTION_ID)
        return BankReconciliationItem(
            bank_transaction_id=transaction.external_id,
            status=(
                BankMatchStatus.CONFLICT if len(exact_id) == 1 else BankMatchStatus.AMBIGUOUS
            ),
            method=BankMatchMethod.TRANSACTION_ID,
        )

    candidates = tuple(event for event in events if _same_values(transaction, event))
    if len(candidates) == 1:
        return _matched(transaction, candidates[0], BankMatchMethod.EXACT_FIELDS)
    if len(candidates) > 1:
        return BankReconciliationItem(
            bank_transaction_id=transaction.external_id,
            status=BankMatchStatus.AMBIGUOUS,
            method=BankMatchMethod.EXACT_FIELDS,
        )
    return BankReconciliationItem(
        bank_transaction_id=transaction.external_id,
        status=BankMatchStatus.MISSING_IN_ACCOUNTING,
        method=BankMatchMethod.NONE,
    )


def _matched(
    transaction: BankTransaction,
    event: FinancialEvent,
    method: BankMatchMethod,
) -> BankReconciliationItem:
    return BankReconciliationItem(
        bank_transaction_id=transaction.external_id,
        status=BankMatchStatus.MATCHED,
        method=method,
        accounting_event_id=event.external_id,
    )


def _same_values(transaction: BankTransaction, event: FinancialEvent) -> bool:
    direction = (
        FinancialDirection.INFLOW
        if transaction.direction is BankTransactionDirection.CREDIT
        else FinancialDirection.OUTFLOW
    )
    is_accounting_fact = (
        event.kind is FinancialEventKind.FACT
        or event.status is FinancialEventStatus.SETTLED
    )
    account_matches = (
        event.account_external_id is None
        or event.account_external_id == transaction.account_external_id
    )
    bank_link_matches = event.bank_transaction_id in (
        None,
        "",
        transaction.external_id,
    )
    return (
        is_accounting_fact
        and event.direction is direction
        and event.amount == transaction.amount
        and event.currency == transaction.currency
        and event.due_date == transaction.booking_date
        and account_matches
        and bank_link_matches
    )


def _statement_issues(
    statement: BankStatement,
    snapshot: FinancialSnapshot,
) -> tuple[SourceDataIssue, ...]:
    issues: list[SourceDataIssue] = []
    if statement.opening_balance is not None and statement.closing_balance is not None:
        movement = sum(
            (
                transaction.amount
                if transaction.direction is BankTransactionDirection.CREDIT
                else -transaction.amount
            )
            for transaction in statement.transactions
            if transaction.status is BankTransactionStatus.BOOKED
        )
        expected = statement.opening_balance + movement
        if expected != statement.closing_balance:
            issues.append(
                _issue(
                    "bank_statement_balance_mismatch",
                    "The bank statement movements do not reconcile to its closing balance.",
                    "The statement may be incomplete or use an unsupported transaction type.",
                    statement.statement_id,
                )
            )
    matching_balances = tuple(
        balance
        for balance in snapshot.balances
        if balance.external_id == statement.account_external_id
        and balance.balance_date == statement.period_end
    )
    if (
        statement.closing_balance is not None
        and len(matching_balances) == 1
        and matching_balances[0].amount != statement.closing_balance
    ):
        issues.append(
            _issue(
                "bank_accounting_balance_mismatch",
                "The bank closing balance differs from the accounting balance for the same date.",
                "The opening cash position requires reconciliation.",
                statement.statement_id,
            )
        )
    return tuple(issues)


def _issue(
    code: str,
    message: str,
    impact: str,
    source_reference: str = "",
) -> SourceDataIssue:
    return SourceDataIssue(
        code=code,
        severity=SourceIssueSeverity.WARNING,
        dataset=DatasetKind.BANK_TRANSACTIONS,
        message=message,
        impact=impact,
        source_reference=source_reference,
    )
