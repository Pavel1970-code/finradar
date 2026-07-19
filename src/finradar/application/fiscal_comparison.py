from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum

from finradar.application.analytical_service import analyze_financial_risk
from finradar.application.fiscal_rules import ActiveFiscalRuleSet
from finradar.domain.financial_snapshot import FinancialSnapshot
from finradar.domain.fiscal import FiscalObligation
from finradar.domain.fiscal_consequences import ViolationEvent
from finradar.domain.forecast import ForecastResult, normalize_money


class FiscalComparisonStatus(str, Enum):
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True, slots=True)
class FiscalComparisonSide:
    rule_id: str
    rule_version: int
    rate: Decimal
    obligation_amount: Decimal
    due_date: date
    forecast: ForecastResult


@dataclass(frozen=True, slots=True)
class FiscalComparison:
    status: FiscalComparisonStatus
    baseline: FiscalComparisonSide | None
    current: FiscalComparisonSide | None
    obligation_delta: Decimal | None
    minimum_balance_delta: Decimal | None
    required_funding_delta: Decimal | None
    reasons: tuple[str, ...] = ()


def compare_fiscal_rules(
    snapshot: FinancialSnapshot,
    *,
    baseline_rules: ActiveFiscalRuleSet,
    current_rules: ActiveFiscalRuleSet,
    as_of: date,
    horizon_days: int,
    violation_events: tuple[ViolationEvent, ...] = (),
) -> FiscalComparison:
    """Compare two deterministic rule sets against the exact same financial snapshot."""

    baseline_analysis = analyze_financial_risk(
        snapshot,
        baseline_rules.obligation_rules,
        as_of=as_of,
        horizon_days=horizon_days,
        penalty_rules=baseline_rules.penalty_rules,
        fine_rules=baseline_rules.fine_rules,
        violation_events=violation_events,
    )
    current_analysis = analyze_financial_risk(
        snapshot,
        current_rules.obligation_rules,
        as_of=as_of,
        horizon_days=horizon_days,
        penalty_rules=current_rules.penalty_rules,
        fine_rules=current_rules.fine_rules,
        violation_events=violation_events,
    )
    baseline_obligations = _calculated_obligations(baseline_analysis.rule_analyses)
    current_obligations = _calculated_obligations(current_analysis.rule_analyses)
    reasons: list[str] = []
    if len(baseline_obligations) != 1:
        reasons.append("Baseline must resolve to exactly one fiscal obligation.")
    if len(current_obligations) != 1:
        reasons.append("Current rules must resolve to exactly one fiscal obligation.")
    if reasons:
        return FiscalComparison(
            status=FiscalComparisonStatus.UNRESOLVED,
            baseline=None,
            current=None,
            obligation_delta=None,
            minimum_balance_delta=None,
            required_funding_delta=None,
            reasons=tuple(reasons),
        )

    baseline = _side(baseline_obligations[0], baseline_analysis.forecast)
    current = _side(current_obligations[0], current_analysis.forecast)
    return FiscalComparison(
        status=FiscalComparisonStatus.RESOLVED,
        baseline=baseline,
        current=current,
        obligation_delta=normalize_money(
            current.obligation_amount - baseline.obligation_amount
        ),
        minimum_balance_delta=normalize_money(
            current.forecast.minimum_balance - baseline.forecast.minimum_balance
        ),
        required_funding_delta=normalize_money(
            current.forecast.required_funding - baseline.forecast.required_funding
        ),
    )


def _calculated_obligations(rule_analyses) -> tuple[FiscalObligation, ...]:
    return tuple(
        item.calculation.obligation
        for item in rule_analyses
        if item.calculation.obligation is not None
    )


def _side(
    obligation: FiscalObligation,
    forecast: ForecastResult,
) -> FiscalComparisonSide:
    return FiscalComparisonSide(
        rule_id=obligation.rule_id,
        rule_version=obligation.rule_version,
        rate=obligation.rate,
        obligation_amount=obligation.amount,
        due_date=obligation.due_date,
        forecast=forecast,
    )
