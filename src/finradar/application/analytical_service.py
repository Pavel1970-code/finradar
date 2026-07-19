from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from finradar.domain.financial_snapshot import (
    FinancialDirection,
    FinancialEvent,
    FinancialEventKind,
    FinancialEventStatus,
    FinancialSnapshot,
)
from finradar.domain.fiscal import (
    ApplicabilityStatus,
    FiscalCalculationResult,
    PercentageFiscalRule,
    ReconciliationAction,
    ReconciliationResult,
    calculate_fiscal_obligation,
    reconcile_fiscal_obligation,
)
from finradar.domain.forecast import ForecastEvent, ForecastResult, calculate_cash_forecast


@dataclass(frozen=True, slots=True)
class RuleAnalysis:
    calculation: FiscalCalculationResult
    reconciliation: ReconciliationResult | None


@dataclass(frozen=True, slots=True)
class AnalyticalResult:
    forecast: ForecastResult
    rule_analyses: tuple[RuleAnalysis, ...]
    forecast_events: tuple[ForecastEvent, ...]


def analyze_financial_risk(
    snapshot: FinancialSnapshot,
    rules: tuple[PercentageFiscalRule, ...],
    *,
    as_of: date,
    horizon_days: int,
) -> AnalyticalResult:
    analyses: list[RuleAnalysis] = []
    reconciled_keys: set[str] = set()
    fiscal_events: list[ForecastEvent] = []

    for rule in rules:
        calculation = calculate_fiscal_obligation(rule, snapshot, as_of=as_of)
        reconciliation = None
        if (
            calculation.applicability.status is ApplicabilityStatus.APPLIED
            and calculation.obligation is not None
        ):
            reconciliation = reconcile_fiscal_obligation(
                calculation.obligation,
                snapshot.events,
            )
            reconciled_keys.add(calculation.obligation.obligation_key)
            if reconciliation.action in {
                ReconciliationAction.ADD_OBLIGATION,
                ReconciliationAction.USE_EXISTING,
            }:
                fiscal_events.append(
                    ForecastEvent(
                        due_date=reconciliation.forecast_due_date,
                        amount=reconciliation.outstanding_amount,
                        is_inflow=False,
                        reference=calculation.obligation.obligation_key,
                    )
                )
        analyses.append(
            RuleAnalysis(calculation=calculation, reconciliation=reconciliation)
        )

    base_events = tuple(
        converted
        for event in snapshot.events
        if event.obligation_key not in reconciled_keys
        if (converted := _to_forecast_event(event)) is not None
    )
    forecast_events = base_events + tuple(fiscal_events)
    opening_balance = sum(
        (balance.amount for balance in snapshot.balances),
        start=Decimal("0.00"),
    )
    forecast = calculate_cash_forecast(
        opening_balance=opening_balance,
        start_date=as_of,
        horizon_days=horizon_days,
        events=forecast_events,
    )
    return AnalyticalResult(
        forecast=forecast,
        rule_analyses=tuple(analyses),
        forecast_events=forecast_events,
    )


def _to_forecast_event(event: FinancialEvent) -> ForecastEvent | None:
    if event.kind is not FinancialEventKind.PLANNED or event.status not in {
        FinancialEventStatus.PLANNED,
        FinancialEventStatus.CONFIRMED,
    }:
        return None
    outstanding = max(event.amount - event.settled_amount, Decimal("0.00"))
    if outstanding == Decimal("0.00"):
        return None
    return ForecastEvent(
        due_date=event.due_date,
        amount=outstanding,
        is_inflow=event.direction is FinancialDirection.INFLOW,
        reference=event.external_id,
    )
