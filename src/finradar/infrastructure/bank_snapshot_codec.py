from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from finradar.domain.banking import (
    BankStatement,
    BankSynchronizationBatch,
    BankTransaction,
    BankTransactionDirection,
    BankTransactionStatus,
)
from finradar.domain.financial_snapshot import (
    DatasetKind,
    SourceDataIssue,
    SourceIssueSeverity,
)


SCHEMA_VERSION = 1


def encode_bank_batch(batch: BankSynchronizationBatch) -> str:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "source_system": batch.source_system,
        "captured_at": batch.captured_at.isoformat(),
        "available": batch.available,
        "next_cursor": batch.next_cursor,
        "statements": [_statement(item) for item in batch.statements],
        "source_issues": [_issue(item) for item in batch.source_issues],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def decode_bank_batch(content_json: str) -> BankSynchronizationBatch:
    payload: dict[str, Any] = json.loads(content_json)
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported bank snapshot schema version.")
    return BankSynchronizationBatch(
        source_system=payload["source_system"],
        captured_at=datetime.fromisoformat(payload["captured_at"]),
        available=payload["available"],
        next_cursor=payload["next_cursor"],
        statements=tuple(
            BankStatement(
                statement_id=item["statement_id"],
                account_external_id=item["account_external_id"],
                period_start=date.fromisoformat(item["period_start"]),
                period_end=date.fromisoformat(item["period_end"]),
                opening_balance=(
                    Decimal(item["opening_balance"])
                    if item["opening_balance"] is not None
                    else None
                ),
                closing_balance=(
                    Decimal(item["closing_balance"])
                    if item["closing_balance"] is not None
                    else None
                ),
                transactions=tuple(_decode_transaction(value) for value in item["transactions"]),
            )
            for item in payload["statements"]
        ),
        source_issues=tuple(
            SourceDataIssue(
                code=item["code"],
                severity=SourceIssueSeverity(item["severity"]),
                dataset=DatasetKind(item["dataset"]),
                message=item["message"],
                impact=item["impact"],
                source_reference=item["source_reference"],
            )
            for item in payload["source_issues"]
        ),
    )


def _statement(statement: BankStatement) -> dict[str, Any]:
    return {
        "statement_id": statement.statement_id,
        "account_external_id": statement.account_external_id,
        "period_start": statement.period_start.isoformat(),
        "period_end": statement.period_end.isoformat(),
        "opening_balance": (
            str(statement.opening_balance) if statement.opening_balance is not None else None
        ),
        "closing_balance": (
            str(statement.closing_balance) if statement.closing_balance is not None else None
        ),
        "transactions": [_transaction(item) for item in statement.transactions],
    }


def _transaction(transaction: BankTransaction) -> dict[str, str]:
    return {
        "external_id": transaction.external_id,
        "account_external_id": transaction.account_external_id,
        "booking_date": transaction.booking_date.isoformat(),
        "value_date": transaction.value_date.isoformat(),
        "direction": transaction.direction.value,
        "amount": str(transaction.amount),
        "currency": transaction.currency,
        "description": transaction.description,
        "reference": transaction.reference,
        "status": transaction.status.value,
        "counterparty_name": transaction.counterparty_name,
        "counterparty_account": transaction.counterparty_account,
        "source_reference": transaction.source_reference,
    }


def _decode_transaction(item: dict[str, Any]) -> BankTransaction:
    return BankTransaction(
        external_id=item["external_id"],
        account_external_id=item["account_external_id"],
        booking_date=date.fromisoformat(item["booking_date"]),
        value_date=date.fromisoformat(item["value_date"]),
        direction=BankTransactionDirection(item["direction"]),
        amount=Decimal(item["amount"]),
        currency=item["currency"],
        description=item["description"],
        reference=item["reference"],
        status=BankTransactionStatus(item["status"]),
        counterparty_name=item["counterparty_name"],
        counterparty_account=item["counterparty_account"],
        source_reference=item["source_reference"],
    )


def _issue(issue: SourceDataIssue) -> dict[str, str]:
    return {
        "code": issue.code,
        "severity": issue.severity.value,
        "dataset": issue.dataset.value,
        "message": issue.message,
        "impact": issue.impact,
        "source_reference": issue.source_reference,
    }
