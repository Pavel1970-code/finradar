from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from finradar.application.accounting_connector import (
    ConnectorCapabilities,
    SynchronizationRequest,
)
from finradar.domain.financial_snapshot import (
    AccountBalance,
    CompanyProfile,
    DatasetKind,
    FinancialDirection,
    FinancialEvent,
    FinancialEventKind,
    FinancialSnapshot,
)


ALL_DATASETS = frozenset(DatasetKind)


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
                    category="receivables",
                    account_external_id="demo-account",
                ),
                FinancialEvent(
                    external_id="demo-payment",
                    title="Fictional supplier payment",
                    amount=Decimal("2000.00"),
                    currency="GEL",
                    due_date=self._as_of + timedelta(days=2),
                    direction=FinancialDirection.OUTFLOW,
                    kind=FinancialEventKind.PLANNED,
                    category="suppliers",
                    account_external_id="demo-account",
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
            events=events,
        )

