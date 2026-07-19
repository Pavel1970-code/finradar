"""Local bank connector fixtures and a bounded delimited-statement adapter."""

from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Mapping

from finradar.application.bank_connector import (
    BankConnectorCapabilities,
    BankSynchronizationRequest,
)
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


MAX_STATEMENT_BYTES = 20 * 1024 * 1024


class FixtureBankConnector:
    def __init__(
        self,
        batch: BankSynchronizationBatch,
        *,
        connection_error: str | None = None,
    ) -> None:
        self._batch = batch
        self._connection_error = connection_error
        self.requests: list[BankSynchronizationRequest] = []

    def capabilities(self) -> BankConnectorCapabilities:
        return BankConnectorCapabilities(
            source_system=self._batch.source_system,
            supported_formats=frozenset({"fixture"}),
            supports_incremental_sync=True,
        )

    def test_connection(self) -> None:
        if self._connection_error is not None:
            raise ConnectionError(self._connection_error)

    def synchronize(self, request: BankSynchronizationRequest) -> BankSynchronizationBatch:
        self.requests.append(request)
        return self._batch


def _csv_fields() -> dict[str, str]:
    return {
        "external_id": "transaction_id",
        "booking_date": "booking_date",
        "value_date": "value_date",
        "direction": "direction",
        "amount": "amount",
        "currency": "currency",
        "description": "description",
        "reference": "reference",
        "status": "status",
        "counterparty_name": "counterparty_name",
        "counterparty_account": "counterparty_account",
    }


@dataclass(frozen=True, slots=True)
class BankCsvMappingProfile:
    profile_id: str
    delimiter: str = ","
    encoding: str = "utf-8-sig"
    fields: Mapping[str, str] = field(default_factory=_csv_fields)
    direction_values: Mapping[str, BankTransactionDirection] = field(
        default_factory=lambda: {
            "credit": BankTransactionDirection.CREDIT,
            "debit": BankTransactionDirection.DEBIT,
        }
    )
    status_values: Mapping[str, BankTransactionStatus] = field(
        default_factory=lambda: {
            "booked": BankTransactionStatus.BOOKED,
            "pending": BankTransactionStatus.PENDING,
            "reversed": BankTransactionStatus.REVERSED,
        }
    )

    def __post_init__(self) -> None:
        if not self.profile_id.strip() or len(self.profile_id) > 100:
            raise ValueError("Bank CSV profile identifier is invalid.")
        if len(self.delimiter) != 1:
            raise ValueError("Bank CSV delimiter must be one character.")


class CsvBankStatementConnector:
    def __init__(
        self,
        *,
        source_system: str,
        statement_path: Path,
        account_external_id: str,
        statement_id: str,
        period_start: date,
        period_end: date,
        mapping: BankCsvMappingProfile,
        opening_balance: Decimal | None = None,
        closing_balance: Decimal | None = None,
    ) -> None:
        if not source_system.strip() or len(source_system) > 100:
            raise ValueError("Bank source-system identifier is invalid.")
        self._source_system = source_system
        self._path = statement_path
        self._account_external_id = account_external_id
        self._statement_id = statement_id
        self._period_start = period_start
        self._period_end = period_end
        self._mapping = mapping
        self._opening_balance = opening_balance
        self._closing_balance = closing_balance

    def capabilities(self) -> BankConnectorCapabilities:
        return BankConnectorCapabilities(
            source_system=self._source_system,
            supported_formats=frozenset({"csv"}),
            supports_incremental_sync=False,
        )

    def test_connection(self) -> None:
        _read_statement(self._path)

    def synchronize(self, request: BankSynchronizationRequest) -> BankSynchronizationBatch:
        if request.cursor is not None:
            raise ValueError("CSV bank connector does not support cursor synchronization.")
        raw = _read_statement(self._path)
        try:
            text = raw.decode(self._mapping.encoding)
        except (LookupError, UnicodeDecodeError) as error:
            raise ValueError("Bank statement encoding is invalid.") from error
        reader = csv.DictReader(io.StringIO(text), delimiter=self._mapping.delimiter)
        if reader.fieldnames is None:
            raise ValueError("Bank statement has no header.")

        transactions: list[BankTransaction] = []
        issues: list[SourceDataIssue] = []
        seen: set[str] = set()
        for line_number, row in enumerate(reader, start=2):
            source_reference = f"{self._path.name}:{line_number}"
            try:
                transaction, derived_id = self._transaction(row, source_reference)
                if request.since is not None and transaction.booking_date < request.since.date():
                    continue
                identity = f"{transaction.account_external_id}\x00{transaction.external_id}"
                if identity in seen:
                    issues.append(
                        _bank_issue(
                            "bank_duplicate_transaction",
                            "The bank statement contains a duplicate transaction.",
                            "The repeated row was excluded from reconciliation.",
                            source_reference,
                        )
                    )
                    continue
                seen.add(identity)
                transactions.append(transaction)
                if derived_id:
                    issues.append(
                        _bank_issue(
                            "bank_transaction_id_derived",
                            "The bank row had no stable transaction identifier.",
                            "FinRadar derived an identity; provider-specific IDs are preferable.",
                            source_reference,
                        )
                    )
            except (KeyError, TypeError, ValueError) as error:
                issues.append(
                    _bank_issue(
                        "bank_row_mapping_failed",
                        f"A bank statement row could not be mapped ({type(error).__name__}).",
                        "The row was excluded and accounting reconciliation may be incomplete.",
                        source_reference,
                    )
                )

        statement = BankStatement(
            statement_id=self._statement_id,
            account_external_id=self._account_external_id,
            period_start=self._period_start,
            period_end=self._period_end,
            opening_balance=self._opening_balance,
            closing_balance=self._closing_balance,
            transactions=tuple(transactions),
        )
        return BankSynchronizationBatch(
            source_system=self._source_system,
            captured_at=datetime.now(timezone.utc),
            available=True,
            statements=(statement,),
            source_issues=tuple(issues),
            next_cursor=hashlib.sha256(raw).hexdigest(),
        )

    def _transaction(
        self,
        row: Mapping[str, object],
        source_reference: str,
    ) -> tuple[BankTransaction, bool]:
        fields = self._mapping.fields
        booking_date = _date(_required(row, fields, "booking_date"))
        value_date_value = _optional(row, fields, "value_date")
        value_date = _date(value_date_value) if value_date_value else booking_date
        direction_text = _text(_required(row, fields, "direction"), 50)
        status_text = _optional_text(_optional(row, fields, "status"), 50) or "booked"
        try:
            direction = self._mapping.direction_values[direction_text]
            status = self._mapping.status_values[status_text]
        except KeyError as error:
            raise ValueError("bank direction or status is not mapped") from error
        amount = _positive_decimal(_required(row, fields, "amount"))
        currency = _currency(_required(row, fields, "currency"))
        description = _optional_text(_optional(row, fields, "description"), 500) or ""
        reference = _optional_text(_optional(row, fields, "reference"), 200) or ""
        external_id = _optional_text(_optional(row, fields, "external_id"), 200)
        derived_id = external_id is None
        if external_id is None:
            identity_input = "\x00".join(
                (
                    self._account_external_id,
                    booking_date.isoformat(),
                    direction.value,
                    str(amount),
                    currency,
                    reference,
                    description,
                )
            )
            external_id = f"derived-{hashlib.sha256(identity_input.encode()).hexdigest()}"
        return (
            BankTransaction(
                external_id=external_id,
                account_external_id=self._account_external_id,
                booking_date=booking_date,
                value_date=value_date,
                direction=direction,
                amount=amount,
                currency=currency,
                description=description,
                reference=reference,
                status=status,
                counterparty_name=_optional_text(
                    _optional(row, fields, "counterparty_name"), 200
                )
                or "",
                counterparty_account=_optional_text(
                    _optional(row, fields, "counterparty_account"), 200
                )
                or "",
                source_reference=source_reference,
            ),
            derived_id,
        )


def _read_statement(path: Path) -> bytes:
    if path.is_symlink():
        raise ValueError("Bank statement cannot be a symbolic link.")
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError as error:
        raise ValueError("Bank statement was not found.") from error
    if not resolved.is_file():
        raise ValueError("Bank statement must be a regular file.")
    if resolved.stat().st_size > MAX_STATEMENT_BYTES:
        raise ValueError("Bank statement exceeds the maximum allowed size.")
    return resolved.read_bytes()


def _required(row: Mapping[str, object], fields: Mapping[str, str], name: str) -> object:
    source = fields[name]
    value = row[source]
    if value is None or value == "":
        raise ValueError(f"required bank field {source} is empty")
    return value


def _optional(
    row: Mapping[str, object], fields: Mapping[str, str], name: str
) -> object | None:
    source = fields.get(name)
    return row.get(source) if source is not None else None


def _text(value: object, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise ValueError("bank text value is invalid")
    return value.strip()


def _optional_text(value: object | None, maximum: int) -> str | None:
    if value is None or value == "":
        return None
    return _text(value, maximum)


def _date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise ValueError("bank date is invalid")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        try:
            return datetime.fromisoformat(value).date()
        except ValueError:
            raise ValueError("bank date is invalid") from error


def _positive_decimal(value: object) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError("bank amount is invalid") from error
    if not parsed.is_finite() or parsed <= Decimal("0"):
        raise ValueError("bank amount must be positive and finite")
    return parsed


def _currency(value: object) -> str:
    currency = _text(value, 3).upper()
    if len(currency) != 3:
        raise ValueError("bank currency is invalid")
    return currency


def _bank_issue(
    code: str,
    message: str,
    impact: str,
    source_reference: str,
) -> SourceDataIssue:
    return SourceDataIssue(
        code=code,
        severity=SourceIssueSeverity.WARNING,
        dataset=DatasetKind.BANK_TRANSACTIONS,
        message=message,
        impact=impact,
        source_reference=source_reference,
    )
