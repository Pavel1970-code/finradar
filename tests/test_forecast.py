from datetime import date, timedelta
from decimal import Decimal

import pytest

from finradar.domain.forecast import (
    ForecastEvent,
    calculate_cash_forecast,
)


START_DATE = date(2026, 7, 18)


def make_event(
    day_offset: int,
    amount: str,
    *,
    is_inflow: bool,
    reference: str,
) -> ForecastEvent:
    return ForecastEvent(
        due_date=START_DATE + timedelta(days=day_offset),
        amount=Decimal(amount),
        is_inflow=is_inflow,
        reference=reference,
    )


def test_detects_demo_cash_gap() -> None:
    events = [
        make_event(
            2,
            "5000.00",
            is_inflow=True,
            reference="Weekend sales",
        ),
        make_event(
            4,
            "6000.00",
            is_inflow=False,
            reference="Supplier",
        ),
        make_event(
            7,
            "3500.00",
            is_inflow=False,
            reference="Rent",
        ),
        make_event(
            9,
            "4000.00",
            is_inflow=True,
            reference="Customer",
        ),
        make_event(
            12,
            "12000.00",
            is_inflow=False,
            reference="Payroll",
        ),
        make_event(
            15,
            "3500.00",
            is_inflow=False,
            reference="Taxes",
        ),
        make_event(
            20,
            "7500.00",
            is_inflow=True,
            reference="Expected sales",
        ),
        make_event(
            25,
            "4000.00",
            is_inflow=False,
            reference="Equipment",
        ),
    ]

    result = calculate_cash_forecast(
        opening_balance=Decimal("15000.00"),
        start_date=START_DATE,
        horizon_days=30,
        events=events,
    )

    assert result.first_gap_date == date(2026, 8, 2)
    assert result.minimum_balance == Decimal("-1000.00")
    assert result.required_funding == Decimal("1000.00")
    assert result.closing_balance == Decimal("2500.00")
    assert len(result.points) == 30


def test_same_day_event_order_does_not_change_result() -> None:
    events = [
        make_event(
            1,
            "50.00",
            is_inflow=True,
            reference="Income",
        ),
        make_event(
            1,
            "200.00",
            is_inflow=False,
            reference="Expense",
        ),
    ]

    direct_result = calculate_cash_forecast(
        opening_balance=Decimal("100.00"),
        start_date=START_DATE,
        horizon_days=3,
        events=events,
    )

    reversed_result = calculate_cash_forecast(
        opening_balance=Decimal("100.00"),
        start_date=START_DATE,
        horizon_days=3,
        events=reversed(events),
    )

    assert direct_result == reversed_result
    assert direct_result.first_gap_date == START_DATE + timedelta(days=1)
    assert direct_result.minimum_balance == Decimal("-50.00")


def test_rejects_negative_event_amount() -> None:
    events = [
        make_event(
            1,
            "-10.00",
            is_inflow=False,
            reference="Invalid payment",
        )
    ]

    with pytest.raises(
        ValueError,
        match="Cash-flow amount cannot be negative",
    ):
        calculate_cash_forecast(
            opening_balance=Decimal("100.00"),
            start_date=START_DATE,
            horizon_days=30,
            events=events,
        )