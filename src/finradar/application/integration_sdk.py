"""Contract checks shared by local accounting and bank adapter implementations."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from collections.abc import Iterable

from finradar.application.accounting_connector import ConnectorCapabilities
from finradar.application.bank_connector import BankConnectorCapabilities
from finradar.domain.banking import BankSynchronizationBatch
from finradar.domain.financial_snapshot import DatasetKind, FinancialSnapshot


class ConnectorContractError(ValueError):
    pass


def validate_accounting_snapshot(
    capabilities: ConnectorCapabilities,
    snapshot: FinancialSnapshot,
) -> FinancialSnapshot:
    _aware(snapshot.captured_at, "Accounting snapshot captured_at")
    if not capabilities.read_only:
        raise ConnectorContractError("FinRadar accepts read-only accounting connectors only.")
    if snapshot.source_system != capabilities.source_system:
        raise ConnectorContractError(
            "Accounting connector returned data for another source system."
        )
    undeclared = snapshot.available_datasets - capabilities.datasets
    if undeclared:
        names = ", ".join(sorted(item.value for item in undeclared))
        raise ConnectorContractError(f"Accounting connector returned undeclared data: {names}.")
    if DatasetKind.BANK_TRANSACTIONS in capabilities.datasets:
        raise ConnectorContractError(
            "Accounting connector must not declare the separate bank dataset."
        )
    if snapshot.company is not None and not snapshot.supplies(DatasetKind.COMPANY_PROFILE):
        raise ConnectorContractError("Company data were returned as unavailable.")
    if snapshot.balances and not snapshot.supplies(DatasetKind.ACCOUNT_BALANCES):
        raise ConnectorContractError("Account balances were returned as unavailable.")
    if snapshot.metrics and not snapshot.supplies(DatasetKind.ACCOUNTING_FACTS):
        raise ConnectorContractError("Accounting metrics were returned as unavailable.")
    if any(item.kind.value == "fact" for item in snapshot.events) and not snapshot.supplies(
        DatasetKind.ACCOUNTING_FACTS
    ):
        raise ConnectorContractError("Accounting events were returned as unavailable.")
    if any(item.kind.value == "planned" for item in snapshot.events) and not snapshot.supplies(
        DatasetKind.PAYMENT_CALENDAR
    ):
        raise ConnectorContractError("Payment events were returned as unavailable.")
    _unique((item.external_id for item in snapshot.balances), "account balance")
    _unique((item.external_id for item in snapshot.events), "financial event")
    for balance in snapshot.balances:
        _finite(balance.amount, "Account balance")
    for metric in snapshot.metrics:
        _finite(metric.amount, "Accounting metric")
    for event in snapshot.events:
        _finite(event.amount, "Financial event")
        _finite(event.settled_amount, "Settled amount")
        if event.amount < Decimal("0") or event.settled_amount < Decimal("0"):
            raise ConnectorContractError("Financial event amounts cannot be negative.")
        if event.counterparty is not None:
            _bounded_text(
                event.counterparty.external_id,
                "Counterparty identifier",
                maximum=200,
            )
            _bounded_text(event.counterparty.name, "Counterparty name", maximum=200)
        if event.payment_purpose:
            _bounded_text(event.payment_purpose, "Payment purpose", maximum=500)
        if event.payment_basis is not None:
            _bounded_text(
                event.payment_basis.document_type,
                "Payment document type",
                maximum=100,
            )
            _bounded_text(
                event.payment_basis.document_number,
                "Payment document number",
                maximum=100,
            )
    if snapshot.source_cursor is not None and (
        not snapshot.source_cursor.strip() or len(snapshot.source_cursor) > 500
    ):
        raise ConnectorContractError("Accounting synchronization cursor is invalid.")
    return snapshot


def validate_bank_batch(
    capabilities: BankConnectorCapabilities,
    batch: BankSynchronizationBatch,
) -> BankSynchronizationBatch:
    _aware(batch.captured_at, "Bank batch captured_at")
    if not batch.source_system.strip() or len(batch.source_system) > 100:
        raise ConnectorContractError("Bank source-system identifier is invalid.")
    if not capabilities.read_only:
        raise ConnectorContractError("FinRadar accepts read-only bank connectors only.")
    if batch.source_system != capabilities.source_system:
        raise ConnectorContractError("Bank connector returned data for another source system.")
    if not batch.available and batch.statements:
        raise ConnectorContractError("Unavailable bank data cannot contain statements.")
    _unique((item.statement_id for item in batch.statements), "bank statement")
    identities = (
        f"{item.account_external_id}\x00{item.external_id}"
        for item in batch.transactions
    )
    _unique(identities, "bank transaction")
    if batch.next_cursor is not None:
        if not batch.next_cursor.strip() or len(batch.next_cursor) > 500:
            raise ConnectorContractError("Bank synchronization cursor is invalid.")
    return batch


def _aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ConnectorContractError(f"{label} must include a timezone.")


def _finite(value: Decimal, label: str) -> None:
    if not value.is_finite():
        raise ConnectorContractError(f"{label} must be finite.")


def _unique(values: Iterable[str], label: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise ConnectorContractError(f"Duplicate {label} identifier: {value}.")
        seen.add(value)


def _bounded_text(value: str, label: str, *, maximum: int) -> None:
    if not value.strip() or len(value.strip()) > maximum:
        raise ConnectorContractError(f"{label} is invalid.")
