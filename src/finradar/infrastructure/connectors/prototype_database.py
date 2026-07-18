from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

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
from finradar.infrastructure.models import (
    CashAccount,
    CashFlowItem,
    Company,
    FlowDirection,
    FlowStatus,
)


class PrototypeDatabaseConnector:
    """Read-only adapter for the current local prototype schema."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def capabilities(self) -> ConnectorCapabilities:
        return ConnectorCapabilities(
            source_system="prototype-sqlite",
            datasets=frozenset(DatasetKind),
            supports_incremental_sync=False,
        )

    def test_connection(self) -> None:
        with self._session_factory() as session:
            session.connection()

    def synchronize(self, request: SynchronizationRequest) -> FinancialSnapshot:
        del request

        with self._session_factory() as session:
            company = session.scalar(select(Company).order_by(Company.created_at).limit(1))
            if company is None:
                return FinancialSnapshot(
                    source_system="prototype-sqlite",
                    captured_at=datetime.now(timezone.utc),
                    available_datasets=frozenset(DatasetKind),
                    company=None,
                )

            accounts = tuple(
                session.scalars(
                    select(CashAccount)
                    .where(CashAccount.company_id == company.id)
                    .order_by(CashAccount.created_at, CashAccount.id)
                )
            )
            items = tuple(
                session.scalars(
                    select(CashFlowItem)
                    .where(CashFlowItem.company_id == company.id)
                    .order_by(CashFlowItem.due_date, CashFlowItem.id)
                )
            )

        account_currencies = {account.id: account.currency for account in accounts}

        return FinancialSnapshot(
            source_system="prototype-sqlite",
            captured_at=datetime.now(timezone.utc),
            available_datasets=frozenset(DatasetKind),
            company=CompanyProfile(
                external_id=company.id,
                name=company.name,
                base_currency=company.base_currency,
            ),
            balances=tuple(
                AccountBalance(
                    external_id=account.id,
                    name=account.name,
                    currency=account.currency,
                    amount=account.current_balance,
                    balance_date=account.balance_date,
                )
                for account in accounts
            ),
            events=tuple(
                FinancialEvent(
                    external_id=item.id,
                    title=item.title,
                    amount=item.amount,
                    currency=account_currencies.get(item.account_id, company.base_currency),
                    due_date=item.due_date,
                    direction=(
                        FinancialDirection.INFLOW
                        if item.direction == FlowDirection.INFLOW
                        else FinancialDirection.OUTFLOW
                    ),
                    kind=(
                        FinancialEventKind.FACT
                        if item.status == FlowStatus.SETTLED
                        else FinancialEventKind.PLANNED
                    ),
                    category=item.category,
                    account_external_id=item.account_id,
                )
                for item in items
                if item.status != FlowStatus.CANCELLED
            ),
        )
