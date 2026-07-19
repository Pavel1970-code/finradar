"""Read-only 1C adapter shell with injectable transport and configurable mapping."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Mapping, Protocol

from finradar.application.accounting_connector import (
    ConnectorCapabilities,
    SynchronizationRequest,
)
from finradar.domain.financial_snapshot import (
    AccountBalance,
    AccountingMetric,
    CompanyProfile,
    DatasetKind,
    FinancialDirection,
    FinancialEvent,
    FinancialEventKind,
    FinancialEventStatus,
    FinancialSnapshot,
    SourceDataIssue,
    SourceIssueSeverity,
)


RawRecord = Mapping[str, object]
ACCOUNTING_DATASETS = frozenset(
    {
        DatasetKind.COMPANY_PROFILE,
        DatasetKind.ACCOUNT_BALANCES,
        DatasetKind.ACCOUNTING_FACTS,
        DatasetKind.PAYMENT_CALENDAR,
    }
)


@dataclass(frozen=True, slots=True)
class OneCExtract:
    captured_at: datetime
    company: RawRecord | None
    balances: tuple[RawRecord, ...] | None
    metrics: tuple[RawRecord, ...] | None
    accounting_events: tuple[RawRecord, ...] | None
    payment_events: tuple[RawRecord, ...] | None
    next_cursor: str | None = None
    source_issues: tuple[SourceDataIssue, ...] = ()


class OneCTransport(Protocol):
    """A concrete OData/HTTP/COM transport can implement this local interface."""

    def test_connection(self) -> None: ...

    def extract(self, request: SynchronizationRequest) -> OneCExtract: ...


def _company_mapping() -> dict[str, str]:
    return {
        "external_id": "external_id",
        "name": "name",
        "base_currency": "base_currency",
        "jurisdiction": "jurisdiction",
        "tax_regime": "tax_regime",
    }


def _balance_mapping() -> dict[str, str]:
    return {
        "external_id": "external_id",
        "name": "name",
        "currency": "currency",
        "amount": "amount",
        "balance_date": "balance_date",
    }


def _metric_mapping() -> dict[str, str]:
    return {
        "code": "code",
        "amount": "amount",
        "currency": "currency",
        "period_start": "period_start",
        "period_end": "period_end",
        "source_reference": "source_reference",
    }


def _event_mapping() -> dict[str, str]:
    return {
        "external_id": "external_id",
        "title": "title",
        "amount": "amount",
        "currency": "currency",
        "due_date": "due_date",
        "direction": "direction",
        "status": "status",
        "settled_amount": "settled_amount",
        "category": "category",
        "account_external_id": "account_external_id",
        "source_reference": "source_reference",
        "bank_transaction_id": "bank_transaction_id",
    }


@dataclass(frozen=True, slots=True)
class OneCMappingProfile:
    profile_id: str
    company_fields: Mapping[str, str] = field(default_factory=_company_mapping)
    balance_fields: Mapping[str, str] = field(default_factory=_balance_mapping)
    metric_fields: Mapping[str, str] = field(default_factory=_metric_mapping)
    event_fields: Mapping[str, str] = field(default_factory=_event_mapping)
    direction_values: Mapping[str, FinancialDirection] = field(
        default_factory=lambda: {
            "inflow": FinancialDirection.INFLOW,
            "outflow": FinancialDirection.OUTFLOW,
        }
    )
    status_values: Mapping[str, FinancialEventStatus] = field(
        default_factory=lambda: {
            "planned": FinancialEventStatus.PLANNED,
            "confirmed": FinancialEventStatus.CONFIRMED,
            "settled": FinancialEventStatus.SETTLED,
            "cancelled": FinancialEventStatus.CANCELLED,
        }
    )

    def __post_init__(self) -> None:
        if not self.profile_id.strip() or len(self.profile_id) > 100:
            raise ValueError("1C mapping profile identifier is invalid.")


class OneCAccountingConnector:
    def __init__(
        self,
        *,
        source_system: str,
        transport: OneCTransport,
        mapping: OneCMappingProfile,
        supports_incremental_sync: bool = True,
    ) -> None:
        if not source_system.strip() or len(source_system) > 100:
            raise ValueError("1C source-system identifier is invalid.")
        self._source_system = source_system
        self._transport = transport
        self._mapping = mapping
        self._supports_incremental_sync = supports_incremental_sync

    def capabilities(self) -> ConnectorCapabilities:
        return ConnectorCapabilities(
            source_system=self._source_system,
            datasets=ACCOUNTING_DATASETS,
            supports_incremental_sync=self._supports_incremental_sync,
        )

    def test_connection(self) -> None:
        self._transport.test_connection()

    def synchronize(self, request: SynchronizationRequest) -> FinancialSnapshot:
        if request.cursor is not None and not self._supports_incremental_sync:
            raise ValueError("This 1C connector does not support cursor synchronization.")
        extract = self._transport.extract(request)
        captured_at = _aware(extract.captured_at, "1C capture time")
        available: set[DatasetKind] = set()
        issues = list(extract.source_issues)

        company = None
        if extract.company is not None:
            available.add(DatasetKind.COMPANY_PROFILE)
            try:
                company = self._company(extract.company)
            except (KeyError, TypeError, ValueError) as error:
                issues.append(
                    _mapping_issue(
                        "one_c_company_mapping_failed",
                        SourceIssueSeverity.ERROR,
                        DatasetKind.COMPANY_PROFILE,
                        "The 1C company record could not be mapped.",
                        "Company identity and fiscal applicability are unavailable.",
                        "company",
                        error,
                    )
                )

        balances = self._records(
            extract.balances,
            dataset=DatasetKind.ACCOUNT_BALANCES,
            label="balance",
            mapper=self._balance,
            available=available,
            issues=issues,
        )
        metrics = self._records(
            extract.metrics,
            dataset=DatasetKind.ACCOUNTING_FACTS,
            label="metric",
            mapper=self._metric,
            available=available,
            issues=issues,
        )
        accounting_events = self._event_records(
            extract.accounting_events,
            kind=FinancialEventKind.FACT,
            dataset=DatasetKind.ACCOUNTING_FACTS,
            label="accounting-event",
            available=available,
            issues=issues,
        )
        payment_events = self._event_records(
            extract.payment_events,
            kind=FinancialEventKind.PLANNED,
            dataset=DatasetKind.PAYMENT_CALENDAR,
            label="payment-event",
            available=available,
            issues=issues,
        )

        return FinancialSnapshot(
            source_system=self._source_system,
            captured_at=captured_at,
            available_datasets=frozenset(available),
            company=company,
            balances=balances,
            metrics=metrics,
            events=accounting_events + payment_events,
            source_issues=tuple(issues),
            source_cursor=extract.next_cursor,
        )

    def _company(self, record: RawRecord) -> CompanyProfile:
        fields = self._mapping.company_fields
        return CompanyProfile(
            external_id=_text(_required(record, fields, "external_id"), 200),
            name=_text(_required(record, fields, "name"), 200),
            base_currency=_currency(_required(record, fields, "base_currency")),
            jurisdiction=_optional_text(_optional(record, fields, "jurisdiction"), 20),
            tax_regime=_optional_text(_optional(record, fields, "tax_regime"), 100),
        )

    def _balance(self, record: RawRecord) -> AccountBalance:
        fields = self._mapping.balance_fields
        return AccountBalance(
            external_id=_text(_required(record, fields, "external_id"), 200),
            name=_text(_required(record, fields, "name"), 200),
            currency=_currency(_required(record, fields, "currency")),
            amount=_decimal(_required(record, fields, "amount")),
            balance_date=_date(_required(record, fields, "balance_date")),
        )

    def _metric(self, record: RawRecord) -> AccountingMetric:
        fields = self._mapping.metric_fields
        period_start = _date(_required(record, fields, "period_start"))
        period_end = _date(_required(record, fields, "period_end"))
        if period_end < period_start:
            raise ValueError("metric period is inverted")
        return AccountingMetric(
            code=_text(_required(record, fields, "code"), 120),
            amount=_decimal(_required(record, fields, "amount")),
            currency=_currency(_required(record, fields, "currency")),
            period_start=period_start,
            period_end=period_end,
            source_reference=_optional_text(
                _optional(record, fields, "source_reference"), 500
            )
            or "",
        )

    def _event(self, record: RawRecord, kind: FinancialEventKind) -> FinancialEvent:
        fields = self._mapping.event_fields
        direction_value = _text(_required(record, fields, "direction"), 50)
        status_value = _optional_text(_optional(record, fields, "status"), 50)
        try:
            direction = self._mapping.direction_values[direction_value]
            status = (
                self._mapping.status_values[status_value]
                if status_value is not None
                else (
                    FinancialEventStatus.SETTLED
                    if kind is FinancialEventKind.FACT
                    else FinancialEventStatus.PLANNED
                )
            )
        except KeyError as error:
            raise ValueError("event direction or status is not mapped") from error
        return FinancialEvent(
            external_id=_text(_required(record, fields, "external_id"), 200),
            title=_text(_required(record, fields, "title"), 200),
            amount=_nonnegative_decimal(_required(record, fields, "amount")),
            currency=_currency(_required(record, fields, "currency")),
            due_date=_date(_required(record, fields, "due_date")),
            direction=direction,
            kind=kind,
            status=status,
            settled_amount=_nonnegative_decimal(
                _optional(record, fields, "settled_amount") or "0"
            ),
            category=_optional_text(_optional(record, fields, "category"), 100),
            account_external_id=_optional_text(
                _optional(record, fields, "account_external_id"), 200
            ),
            source_reference=_optional_text(
                _optional(record, fields, "source_reference"), 500
            )
            or "",
            bank_transaction_id=_optional_text(
                _optional(record, fields, "bank_transaction_id"), 200
            ),
        )

    def _records(self, records, *, dataset, label, mapper, available, issues):
        if records is None:
            return ()
        available.add(dataset)
        mapped = []
        for index, record in enumerate(records, start=1):
            try:
                mapped.append(mapper(record))
            except (KeyError, TypeError, ValueError) as error:
                issues.append(
                    _mapping_issue(
                        f"one_c_{label.replace('-', '_')}_mapping_failed",
                        SourceIssueSeverity.WARNING,
                        dataset,
                        f"A 1C {label} record could not be mapped.",
                        "The record was excluded and the forecast may be incomplete.",
                        f"{label}:{index}",
                        error,
                    )
                )
        return tuple(mapped)

    def _event_records(
        self,
        records,
        *,
        kind,
        dataset,
        label,
        available,
        issues,
    ):
        return self._records(
            records,
            dataset=dataset,
            label=label,
            mapper=lambda record: self._event(record, kind),
            available=available,
            issues=issues,
        )


class FixtureOneCTransport:
    """Deterministic test transport; contains no network or 1C runtime dependency."""

    def __init__(self, extract: OneCExtract, *, connection_error: str | None = None) -> None:
        self._extract = extract
        self._connection_error = connection_error
        self.requests: list[SynchronizationRequest] = []

    def test_connection(self) -> None:
        if self._connection_error is not None:
            raise ConnectionError(self._connection_error)

    def extract(self, request: SynchronizationRequest) -> OneCExtract:
        self.requests.append(request)
        return self._extract


def _required(record: RawRecord, fields: Mapping[str, str], canonical: str) -> object:
    source = fields[canonical]
    value = record[source]
    if value is None:
        raise ValueError(f"required field {source} is null")
    return value


def _optional(record: RawRecord, fields: Mapping[str, str], canonical: str) -> object | None:
    source = fields.get(canonical)
    return record.get(source) if source is not None else None


def _text(value: object, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise ValueError("text value is invalid")
    return value.strip()


def _optional_text(value: object | None, maximum: int) -> str | None:
    if value is None or value == "":
        return None
    return _text(value, maximum)


def _currency(value: object) -> str:
    currency = _text(value, 3).upper()
    if len(currency) != 3:
        raise ValueError("currency is invalid")
    return currency


def _decimal(value: object) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError("decimal value is invalid") from error
    if not parsed.is_finite():
        raise ValueError("decimal value must be finite")
    return parsed


def _nonnegative_decimal(value: object) -> Decimal:
    parsed = _decimal(value)
    if parsed < Decimal("0"):
        raise ValueError("amount cannot be negative")
    return parsed


def _date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise ValueError("date value is invalid")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        try:
            return datetime.fromisoformat(value).date()
        except ValueError:
            raise ValueError("date value is invalid") from error


def _aware(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must include a timezone")
    return value.astimezone(timezone.utc)


def _mapping_issue(
    code: str,
    severity: SourceIssueSeverity,
    dataset: DatasetKind,
    message: str,
    impact: str,
    source_reference: str,
    error: Exception,
) -> SourceDataIssue:
    return SourceDataIssue(
        code=code,
        severity=severity,
        dataset=dataset,
        message=f"{message} ({type(error).__name__})",
        impact=impact,
        source_reference=source_reference,
    )
