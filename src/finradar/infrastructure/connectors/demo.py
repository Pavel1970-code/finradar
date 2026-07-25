from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from finradar.application.accounting_connector import (
    ConnectorCapabilities,
    SynchronizationRequest,
)
from finradar.domain.financial_snapshot import (
    AccountBalance,
    AccountingMetric,
    CompanyProfile,
    CounterpartyKind,
    CounterpartyReference,
    DatasetKind,
    FinancialDirection,
    FinancialEvent,
    FinancialEventKind,
    FinancialEventStatus,
    FinancialSnapshot,
    PaymentBasis,
)


ALL_DATASETS = frozenset(
    {
        DatasetKind.COMPANY_PROFILE,
        DatasetKind.ACCOUNT_BALANCES,
        DatasetKind.ACCOUNTING_FACTS,
        DatasetKind.PAYMENT_CALENDAR,
    }
)


class DemoAccountingConnector:
    """Deterministic reference adapter used without an external system."""

    def __init__(
        self,
        *,
        as_of: date,
        unavailable_datasets: frozenset[DatasetKind] = frozenset(),
    ) -> None:
        self._as_of = as_of
        self._available_datasets = ALL_DATASETS - unavailable_datasets

    def capabilities(self) -> ConnectorCapabilities:
        return ConnectorCapabilities(
            source_system="demo-reference",
            datasets=ALL_DATASETS,
            supports_incremental_sync=False,
        )

    def test_connection(self) -> None:
        return None

    def synchronize(self, request: SynchronizationRequest) -> FinancialSnapshot:
        del request

        company = (
            CompanyProfile(
                external_id="demo-company",
                name="Fictional Connector Company",
                base_currency="GEL",
                jurisdiction="GE",
                tax_regime="fictional-demo-regime",
            )
            if DatasetKind.COMPANY_PROFILE in self._available_datasets
            else None
        )

        balances = (
            (
                AccountBalance(
                    external_id="demo-account",
                    name="Fictional operating account",
                    currency="GEL",
                    amount=Decimal("1000.00"),
                    balance_date=self._as_of,
                ),
            )
            if DatasetKind.ACCOUNT_BALANCES in self._available_datasets
            else ()
        )

        events = (
            (
                FinancialEvent(
                    external_id="demo-receipt",
                    title="Fictional customer receipt",
                    amount=Decimal("500.00"),
                    currency="GEL",
                    due_date=self._as_of + timedelta(days=1),
                    direction=FinancialDirection.INFLOW,
                    kind=FinancialEventKind.PLANNED,
                    status=FinancialEventStatus.CONFIRMED,
                    category="receivables",
                    account_external_id="demo-account",
                    counterparty=CounterpartyReference(
                        external_id="demo-customer",
                        name="Fictional customer",
                        kind=CounterpartyKind.CUSTOMER,
                    ),
                    payment_purpose="Payment for fictional goods",
                    payment_basis=PaymentBasis(
                        document_type="invoice",
                        document_number="DEMO-001",
                        document_date=self._as_of - timedelta(days=5),
                    ),
                ),
                FinancialEvent(
                    external_id="demo-payment",
                    title="Fictional supplier payment",
                    amount=Decimal("2000.00"),
                    currency="GEL",
                    due_date=self._as_of + timedelta(days=2),
                    direction=FinancialDirection.OUTFLOW,
                    kind=FinancialEventKind.PLANNED,
                    status=FinancialEventStatus.CONFIRMED,
                    category="suppliers",
                    account_external_id="demo-account",
                    counterparty=CounterpartyReference(
                        external_id="demo-supplier",
                        name="Fictional supplier",
                        kind=CounterpartyKind.SUPPLIER,
                    ),
                    payment_purpose="Payment for fictional delivery",
                    payment_basis=PaymentBasis(
                        document_type="delivery_note",
                        document_number="DEMO-002",
                        document_date=self._as_of - timedelta(days=4),
                    ),
                ),
            )
            if DatasetKind.PAYMENT_CALENDAR in self._available_datasets
            else ()
        )

        return FinancialSnapshot(
            source_system="demo-reference",
            captured_at=datetime.combine(self._as_of, time(), tzinfo=timezone.utc),
            available_datasets=self._available_datasets,
            company=company,
            balances=balances,
            metrics=(
                AccountingMetric(
                    code="fictional_taxable_revenue",
                    amount=Decimal("10000.00"),
                    currency="GEL",
                    period_start=self._as_of - timedelta(days=30),
                    period_end=self._as_of - timedelta(days=1),
                    source_reference="demo-ledger",
                ),
            )
            if DatasetKind.ACCOUNTING_FACTS in self._available_datasets
            else (),
            events=events,
        )
