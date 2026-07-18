from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP


CENT = Decimal("0.01")
ZERO = Decimal("0.00")


def normalize_money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True, slots=True)
class ForecastEvent:
    due_date: date
    amount: Decimal
    is_inflow: bool
    reference: str = ""


@dataclass(frozen=True, slots=True)
class ForecastPoint:
    day: date
    inflow: Decimal
    outflow: Decimal
    closing_balance: Decimal


@dataclass(frozen=True, slots=True)
class ForecastResult:
    start_date: date
    end_date: date
    opening_balance: Decimal
    closing_balance: Decimal
    minimum_balance: Decimal
    first_gap_date: date | None
    required_funding: Decimal
    points: tuple[ForecastPoint, ...]


def calculate_cash_forecast(
    *,
    opening_balance: Decimal,
    start_date: date,
    horizon_days: int,
    events: Iterable[ForecastEvent],
) -> ForecastResult:
    if horizon_days <= 0:
        raise ValueError("Forecast horizon must be greater than zero.")

    normalized_opening_balance = normalize_money(opening_balance)
    end_date = start_date + timedelta(days=horizon_days - 1)

    daily_inflows: dict[date, Decimal] = defaultdict(lambda: ZERO)
    daily_outflows: dict[date, Decimal] = defaultdict(lambda: ZERO)

    for event in events:
        amount = normalize_money(event.amount)

        if amount < ZERO:
            raise ValueError(
                f"Cash-flow amount cannot be negative: {event.reference}"
            )

        if event.due_date < start_date or event.due_date > end_date:
            continue

        if event.is_inflow:
            daily_inflows[event.due_date] += amount
        else:
            daily_outflows[event.due_date] += amount

    balance = normalized_opening_balance
    minimum_balance = normalized_opening_balance
    first_gap_date: date | None = None
    points: list[ForecastPoint] = []

    for day_offset in range(horizon_days):
        current_day = start_date + timedelta(days=day_offset)

        inflow = normalize_money(daily_inflows[current_day])
        outflow = normalize_money(daily_outflows[current_day])
        balance = normalize_money(balance + inflow - outflow)

        if balance < minimum_balance:
            minimum_balance = balance

        if balance < ZERO and first_gap_date is None:
            first_gap_date = current_day

        points.append(
            ForecastPoint(
                day=current_day,
                inflow=inflow,
                outflow=outflow,
                closing_balance=balance,
            )
        )

    required_funding = (
        normalize_money(-minimum_balance)
        if minimum_balance < ZERO
        else ZERO
    )

    return ForecastResult(
        start_date=start_date,
        end_date=end_date,
        opening_balance=normalized_opening_balance,
        closing_balance=balance,
        minimum_balance=minimum_balance,
        first_gap_date=first_gap_date,
        required_funding=required_funding,
        points=tuple(points),
    )