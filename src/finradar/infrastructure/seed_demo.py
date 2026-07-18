from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from finradar.infrastructure.database import (
    SessionLocal,
    initialize_database,
)
from finradar.infrastructure.models import (
    CashAccount,
    CashFlowItem,
    Company,
    FlowDirection,
    FlowStatus,
)


DEMO_COMPANY_NAME = "Demo Restaurant Tbilisi"


def seed_demo_data() -> bool:
    initialize_database()

    with SessionLocal() as session:
        existing_company = session.scalar(
            select(Company).where(
                Company.name == DEMO_COMPANY_NAME
            )
        )

        if existing_company is not None:
            print("Demo data already exists.")
            return False

        today = date.today()

        company = Company(
            name=DEMO_COMPANY_NAME,
            base_currency="GEL",
        )

        account = CashAccount(
            company=company,
            name="Основной расчётный счёт",
            currency="GEL",
            current_balance=Decimal("15000.00"),
            balance_date=today,
        )

        cash_flow_items = [
            CashFlowItem(
                company=company,
                account=account,
                title="Выручка за выходные",
                category="sales",
                direction=FlowDirection.INFLOW,
                status=FlowStatus.CONFIRMED,
                amount=Decimal("5000.00"),
                due_date=today + timedelta(days=2),
                source="demo_seed",
            ),
            CashFlowItem(
                company=company,
                account=account,
                title="Платёж поставщику продуктов",
                category="suppliers",
                direction=FlowDirection.OUTFLOW,
                status=FlowStatus.CONFIRMED,
                amount=Decimal("6000.00"),
                due_date=today + timedelta(days=4),
                source="demo_seed",
            ),
            CashFlowItem(
                company=company,
                account=account,
                title="Аренда помещения",
                category="rent",
                direction=FlowDirection.OUTFLOW,
                status=FlowStatus.CONFIRMED,
                amount=Decimal("3500.00"),
                due_date=today + timedelta(days=7),
                source="demo_seed",
            ),
            CashFlowItem(
                company=company,
                account=account,
                title="Оплата корпоративного клиента",
                category="receivables",
                direction=FlowDirection.INFLOW,
                status=FlowStatus.PLANNED,
                amount=Decimal("4000.00"),
                due_date=today + timedelta(days=9),
                source="demo_seed",
            ),
            CashFlowItem(
                company=company,
                account=account,
                title="Заработная плата",
                category="payroll",
                direction=FlowDirection.OUTFLOW,
                status=FlowStatus.CONFIRMED,
                amount=Decimal("12000.00"),
                due_date=today + timedelta(days=12),
                source="demo_seed",
            ),
            CashFlowItem(
                company=company,
                account=account,
                title="Налоговый платёж",
                category="taxes",
                direction=FlowDirection.OUTFLOW,
                status=FlowStatus.CONFIRMED,
                amount=Decimal("3500.00"),
                due_date=today + timedelta(days=15),
                source="demo_seed",
            ),
            CashFlowItem(
                company=company,
                account=account,
                title="Ожидаемая выручка",
                category="sales",
                direction=FlowDirection.INFLOW,
                status=FlowStatus.PLANNED,
                amount=Decimal("7500.00"),
                due_date=today + timedelta(days=20),
                source="demo_seed",
            ),
            CashFlowItem(
                company=company,
                account=account,
                title="Покупка оборудования",
                category="equipment",
                direction=FlowDirection.OUTFLOW,
                status=FlowStatus.PLANNED,
                amount=Decimal("4000.00"),
                due_date=today + timedelta(days=25),
                source="demo_seed",
            ),
        ]

        session.add(company)
        session.add(account)
        session.add_all(cash_flow_items)
        session.commit()

        print("Demo company and cash-flow data created.")
        return True


if __name__ == "__main__":
    seed_demo_data()