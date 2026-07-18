from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from finradar.application.accounting_connector import SynchronizationRequest
from finradar.domain.financial_snapshot import FinancialEventKind
from finradar.infrastructure.connectors.prototype_database import (
    PrototypeDatabaseConnector,
)
from finradar.infrastructure.database import Base
from finradar.infrastructure.models import (
    CashAccount,
    CashFlowItem,
    Company,
    FlowDirection,
    FlowStatus,
)


def test_prototype_connector_maps_current_schema_without_writing() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    with session_factory() as session:
        company = Company(name="Fictional Company", base_currency="GEL")
        account = CashAccount(
            company=company,
            name="Main",
            currency="GEL",
            current_balance=Decimal("1200.00"),
            balance_date=date(2026, 7, 18),
        )
        session.add_all(
            [
                company,
                account,
                CashFlowItem(
                    company=company,
                    account=account,
                    title="Future payment",
                    category="suppliers",
                    direction=FlowDirection.OUTFLOW,
                    status=FlowStatus.CONFIRMED,
                    amount=Decimal("500.00"),
                    due_date=date(2026, 7, 20),
                ),
                CashFlowItem(
                    company=company,
                    account=account,
                    title="Cancelled payment",
                    category="suppliers",
                    direction=FlowDirection.OUTFLOW,
                    status=FlowStatus.CANCELLED,
                    amount=Decimal("900.00"),
                    due_date=date(2026, 7, 21),
                ),
            ]
        )
        session.commit()

    snapshot = PrototypeDatabaseConnector(session_factory).synchronize(
        SynchronizationRequest()
    )

    assert snapshot.company is not None
    assert snapshot.company.name == "Fictional Company"
    assert snapshot.balances[0].amount == Decimal("1200.00")
    assert len(snapshot.events) == 1
    assert snapshot.events[0].kind is FinancialEventKind.PLANNED
    assert snapshot.events[0].currency == "GEL"

