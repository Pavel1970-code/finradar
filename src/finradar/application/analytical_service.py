from dataclasses import dataclass
from datetime import date, timedelta
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
    FiscalObligation,
    FiscalObligationRule,
    ReconciliationAction,
    ReconciliationResult,
    calculate_fiscal_obligation,
    reconcile_fiscal_obligation,
)
from finradar.domain.fiscal_consequences import (
    ConsequenceStatus,
    FineRule,
    FiscalConsequence,
    LatePaymentPenaltyRule,
    ViolationEvent,
    accrued_consequence_from_event,
    calculate_fine,
    calculate_late_payment_penalty,
)
from finradar.domain.forecast import ForecastEvent, ForecastResult, calculate_cash_forecast


@dataclass(frozen=True, slots=True)
class RuleAnalysis:
    calculation: FiscalCalculationResult
    reconciliation: ReconciliationResult | None


@dataclass(frozen=True, slots=True)
class AnalyticalResult:
    forecast: ForecastResult
    stress_forecast: ForecastResult
    rule_analyses: tuple[RuleAnalysis, ...]
    forecast_events: tuple[ForecastEvent, ...]
    stress_forecast_events: tuple[ForecastEvent, ...]
    consequences: tuple[FiscalConsequence, ...]


def analyze_financial_risk(
    snapshot: FinancialSnapshot,
    rules: tuple[FiscalObligationRule, ...],
    *,
    as_of: date,
    horizon_days: int,
    penalty_rules: tuple[LatePaymentPenaltyRule, ...] = (),
    fine_rules: tuple[FineRule, ...] = (),
    violation_events: tuple[ViolationEvent, ...] = (),
    stress_overdue_days: int = 0,
) -> AnalyticalResult:
    if stress_overdue_days < 0:
        raise ValueError("Stress overdue days cannot be negative.")

    analyses: list[RuleAnalysis] = []
    reconciled_keys: set[str] = set()
    fiscal_events: list[ForecastEvent] = []
    base_consequence_events: list[ForecastEvent] = []
    stress_consequence_events: list[ForecastEvent] = []
    consequences: list[FiscalConsequence] = [
        consequence
        for event in snapshot.events
        if (consequence := accrued_consequence_from_event(event)) is not None
    ]

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
                        due_date=max(reconciliation.forecast_due_date, as_of),
                        amount=reconciliation.outstanding_amount,
                        is_inflow=False,
                        reference=calculation.obligation.obligation_key,
                    )
                )
            calculated, contingent = _analyze_consequences(
                calculation.obligation,
                reconciliation,
                snapshot=snapshot,
                as_of=as_of,
                penalty_rules=penalty_rules,
                fine_rules=fine_rules,
                violation_events=violation_events,
                stress_overdue_days=stress_overdue_days,
            )
            consequences.extend(calculated)
            consequences.extend(contingent)
            base_consequence_events.extend(
                event
                for consequence in calculated
                if (event := _consequence_to_event(consequence, as_of=as_of)) is not None
            )
            contingent_identities = {
                (item.consequence_type, item.related_obligation_key)
                for item in contingent
            }
            stress_consequences = contingent + tuple(
                item
                for item in calculated
                if (item.consequence_type, item.related_obligation_key)
                not in contingent_identities
            )
            stress_consequence_events.extend(
                event
                for consequence in stress_consequences
                if (event := _consequence_to_event(consequence, as_of=as_of)) is not None
            )
        analyses.append(
            RuleAnalysis(calculation=calculation, reconciliation=reconciliation)
        )

    base_events = tuple(
        converted
        for event in snapshot.events
        if event.obligation_key not in reconciled_keys
        if (converted := _to_forecast_event(event, as_of=as_of)) is not None
    )
    forecast_events = base_events + tuple(fiscal_events) + tuple(base_consequence_events)
    stress_forecast_events = (
        base_events + tuple(fiscal_events) + tuple(stress_consequence_events)
    )
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
    stress_forecast = calculate_cash_forecast(
        opening_balance=opening_balance,
        start_date=as_of,
        horizon_days=horizon_days,
        events=stress_forecast_events,
    )
    return AnalyticalResult(
        forecast=forecast,
        stress_forecast=stress_forecast,
        rule_analyses=tuple(analyses),
        forecast_events=forecast_events,
        stress_forecast_events=stress_forecast_events,
        consequences=tuple(consequences),
    )


def _to_forecast_event(event: FinancialEvent, *, as_of: date) -> ForecastEvent | None:
    if event.kind is not FinancialEventKind.PLANNED or event.status not in {
        FinancialEventStatus.PLANNED,
        FinancialEventStatus.CONFIRMED,
    }:
        return None
    outstanding = max(event.amount - event.settled_amount, Decimal("0.00"))
    if outstanding == Decimal("0.00"):
        return None
    return ForecastEvent(
        due_date=max(event.due_date, as_of),
        amount=outstanding,
        is_inflow=event.direction is FinancialDirection.INFLOW,
        reference=event.external_id,
    )


def _analyze_consequences(
    obligation: FiscalObligation,
    reconciliation: ReconciliationResult,
    *,
    snapshot: FinancialSnapshot,
    as_of: date,
    penalty_rules: tuple[LatePaymentPenaltyRule, ...],
    fine_rules: tuple[FineRule, ...],
    violation_events: tuple[ViolationEvent, ...],
    stress_overdue_days: int,
) -> tuple[tuple[FiscalConsequence, ...], tuple[FiscalConsequence, ...]]:
    calculated: list[FiscalConsequence] = []
    contingent: list[FiscalConsequence] = []
    if reconciliation.outstanding_amount == Decimal("0.00"):
        return (), ()

    for rule in penalty_rules:
        if obligation.due_date < as_of:
            consequence = calculate_late_payment_penalty(
                rule,
                obligation,
                outstanding_amount=reconciliation.outstanding_amount,
                overdue_through=as_of,
                status=ConsequenceStatus.CALCULATED,
            )
            if consequence is not None:
                calculated.append(consequence)

        if stress_overdue_days > 0:
            stress_end = max(as_of, obligation.due_date) + timedelta(
                days=stress_overdue_days
            )
            consequence = calculate_late_payment_penalty(
                rule,
                obligation,
                outstanding_amount=reconciliation.outstanding_amount,
                overdue_through=stress_end,
                status=ConsequenceStatus.CONTINGENT,
            )
            if consequence is not None:
                contingent.append(consequence)

    relevant_violations = (
        item for item in violation_events if item.obligation_key == obligation.obligation_key
    )
    for violation in relevant_violations:
        for rule in fine_rules:
            consequence = calculate_fine(
                rule,
                violation,
                obligation,
                outstanding_amount=reconciliation.outstanding_amount,
            )
            if consequence is None:
                continue
            target = (
                calculated
                if consequence.status is ConsequenceStatus.CALCULATED
                else contingent
            )
            target.append(consequence)

    recorded_keys = {
        event.obligation_key
        for event in snapshot.events
        if event.status is not FinancialEventStatus.CANCELLED
    }
    calculated = [
        item for item in calculated if item.consequence_key not in recorded_keys
    ]
    contingent = [
        item for item in contingent if item.consequence_key not in recorded_keys
    ]
    return tuple(calculated), tuple(contingent)


def _consequence_to_event(
    consequence: FiscalConsequence,
    *,
    as_of: date,
) -> ForecastEvent | None:
    if consequence.amount is None or consequence.status is ConsequenceStatus.UNRESOLVED:
        return None
    return ForecastEvent(
        due_date=max(consequence.assessment_date, as_of),
        amount=consequence.amount,
        is_inflow=False,
        reference=consequence.consequence_key,
    )
