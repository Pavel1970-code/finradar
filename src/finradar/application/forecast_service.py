from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from finradar.domain.forecast import (
    ForecastEvent,
    ForecastResult,
    calculate_cash_forecast,
)
from finradar.infrastructure.database import SessionLocal
from finradar.infrastructure.models import (
    CashAccount,
    CashFlowItem,
    Company,
    FlowDirection,
    FlowStatus,
)


@dataclass(frozen=True, slots=True)
class CompanyForecast:
    company_id: str
    company_name: str
    currency: str
    account_count: int
    event_count: int
    result: ForecastResult


def load_company_forecast(
    *,
    horizon_days: int = 30,
) -> CompanyForecast | None:
    start_date = date.today()
    end_date = start_date + timedelta(days=horizon_days - 1)

    with SessionLocal() as session:
        company = session.scalar(
            select(Company)
            .order_by(Company.created_at)
            .limit(1)
        )

        if company is None:
            return None

        accounts = list(
            session.scalars(
                select(CashAccount).where(
                    CashAccount.company_id == company.id
                )
            )
        )

        incompatible_accounts = [
            account
            for account in accounts
            if account.currency != company.base_currency
        ]

        if incompatible_accounts:
            raise ValueError(
                "Currency conversion is required before calculating "
                "a consolidated forecast."
            )

        opening_balance = sum(
            (
                account.current_balance
                for account in accounts
            ),
            start=Decimal("0.00"),
        )

        cash_flow_items = list(
            session.scalars(
                select(CashFlowItem)
                .where(
                    CashFlowItem.company_id == company.id,
                    CashFlowItem.due_date >= start_date,
                    CashFlowItem.due_date <= end_date,
                    CashFlowItem.status.in_(
                        [
                            FlowStatus.PLANNED,
                            FlowStatus.CONFIRMED,
                        ]
                    ),
                )
                .order_by(
                    CashFlowItem.due_date,
                    CashFlowItem.id,
                )
            )
        )

        events = [
            ForecastEvent(
                due_date=item.due_date,
                amount=item.amount,
                is_inflow=(
                    item.direction == FlowDirection.INFLOW
                ),
                reference=item.id,
            )
            for item in cash_flow_items
        ]

        result = calculate_cash_forecast(
            opening_balance=opening_balance,
            start_date=start_date,
            horizon_days=horizon_days,
            events=events,
        )

        return CompanyForecast(
            company_id=company.id,
            company_name=company.name,
            currency=company.base_currency,
            account_count=len(accounts),
            event_count=len(cash_flow_items),
            result=result,
        )