from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from enum import Enum

from finradar.domain.financial_snapshot import (
    AccountingMetric,
    FinancialEvent,
    FinancialEventStatus,
    FinancialSnapshot,
)
from finradar.domain.forecast import normalize_money


class FiscalRuleStatus(str, Enum):
    CANDIDATE = "candidate"
    VALIDATED = "validated"
    REVIEWED = "reviewed"
    ACTIVE = "active"
    SUPERSEDED = "superseded"


class ApplicabilityStatus(str, Enum):
    APPLIED = "applied"
    NOT_APPLICABLE = "not_applicable"
    UNRESOLVED = "unresolved"


class ReconciliationAction(str, Enum):
    ADD_OBLIGATION = "add_obligation"
    USE_EXISTING = "use_existing"
    ALREADY_SETTLED = "already_settled"


@dataclass(frozen=True, slots=True)
class PercentageFiscalRule:
    rule_id: str
    version: int
    title: str
    jurisdiction: str
    tax_regimes: frozenset[str]
    effective_from: date
    effective_to: date | None
    base_metric_code: str
    rate: Decimal
    payment_days_after_period_end: int
    obligation_category: str
    source_reference: str
    status: FiscalRuleStatus = FiscalRuleStatus.CANDIDATE


@dataclass(frozen=True, slots=True)
class ApplicabilityResult:
    status: ApplicabilityStatus
    reasons: tuple[str, ...]
    missing_fields: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FiscalObligation:
    obligation_key: str
    rule_id: str
    rule_version: int
    title: str
    amount: Decimal
    currency: str
    due_date: date
    category: str
    base_amount: Decimal
    rate: Decimal
    source_reference: str
    explanation: str


@dataclass(frozen=True, slots=True)
class FiscalCalculationResult:
    applicability: ApplicabilityResult
    obligation: FiscalObligation | None


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    action: ReconciliationAction
    obligation: FiscalObligation
    matching_event_ids: tuple[str, ...]
    outstanding_amount: Decimal
    forecast_due_date: date


def assess_rule_applicability(
    rule: PercentageFiscalRule,
    snapshot: FinancialSnapshot,
    *,
    as_of: date,
) -> ApplicabilityResult:
    if rule.status is not FiscalRuleStatus.ACTIVE:
        return ApplicabilityResult(
            status=ApplicabilityStatus.NOT_APPLICABLE,
            reasons=("The rule is not active.",),
        )

    if as_of < rule.effective_from or (
        rule.effective_to is not None and as_of > rule.effective_to
    ):
        return ApplicabilityResult(
            status=ApplicabilityStatus.NOT_APPLICABLE,
            reasons=("The rule is not effective on the analysis date.",),
        )

    if snapshot.company is None:
        return ApplicabilityResult(
            status=ApplicabilityStatus.UNRESOLVED,
            reasons=("Company profile is missing.",),
            missing_fields=("company_profile",),
        )

    missing_fields: list[str] = []
    if snapshot.company.jurisdiction is None:
        missing_fields.append("company.jurisdiction")
    if snapshot.company.tax_regime is None:
        missing_fields.append("company.tax_regime")
    if missing_fields:
        return ApplicabilityResult(
            status=ApplicabilityStatus.UNRESOLVED,
            reasons=("Company attributes required by the rule are missing.",),
            missing_fields=tuple(missing_fields),
        )

    if snapshot.company.jurisdiction != rule.jurisdiction:
        return ApplicabilityResult(
            status=ApplicabilityStatus.NOT_APPLICABLE,
            reasons=("Company jurisdiction does not match the rule.",),
        )
    if snapshot.company.tax_regime not in rule.tax_regimes:
        return ApplicabilityResult(
            status=ApplicabilityStatus.NOT_APPLICABLE,
            reasons=("Company tax regime does not match the rule.",),
        )

    return ApplicabilityResult(
        status=ApplicabilityStatus.APPLIED,
        reasons=("The active rule matches company jurisdiction and tax regime.",),
    )


def calculate_fiscal_obligation(
    rule: PercentageFiscalRule,
    snapshot: FinancialSnapshot,
    *,
    as_of: date,
) -> FiscalCalculationResult:
    applicability = assess_rule_applicability(rule, snapshot, as_of=as_of)
    if applicability.status is not ApplicabilityStatus.APPLIED:
        return FiscalCalculationResult(applicability=applicability, obligation=None)

    metric = _latest_metric(snapshot.metrics, rule.base_metric_code, as_of)
    if metric is None:
        return FiscalCalculationResult(
            applicability=ApplicabilityResult(
                status=ApplicabilityStatus.UNRESOLVED,
                reasons=("The accounting metric required for calculation is missing.",),
                missing_fields=(f"accounting_metric:{rule.base_metric_code}",),
            ),
            obligation=None,
        )

    assert snapshot.company is not None
    if metric.currency != snapshot.company.base_currency:
        return FiscalCalculationResult(
            applicability=ApplicabilityResult(
                status=ApplicabilityStatus.UNRESOLVED,
                reasons=("The accounting metric currency differs from company currency.",),
                missing_fields=("currency_conversion_policy",),
            ),
            obligation=None,
        )
    if metric.amount < Decimal("0.00"):
        return FiscalCalculationResult(
            applicability=ApplicabilityResult(
                status=ApplicabilityStatus.UNRESOLVED,
                reasons=("A percentage obligation cannot use a negative tax base.",),
                missing_fields=(f"valid_metric:{rule.base_metric_code}",),
            ),
            obligation=None,
        )

    amount = normalize_money(metric.amount * rule.rate)
    obligation_key = (
        f"{rule.rule_id}:{metric.period_start.isoformat()}:{metric.period_end.isoformat()}"
    )
    obligation = FiscalObligation(
        obligation_key=obligation_key,
        rule_id=rule.rule_id,
        rule_version=rule.version,
        title=rule.title,
        amount=amount,
        currency=metric.currency,
        due_date=metric.period_end + timedelta(days=rule.payment_days_after_period_end),
        category=rule.obligation_category,
        base_amount=normalize_money(metric.amount),
        rate=rule.rate,
        source_reference=rule.source_reference,
        explanation=(
            f"{normalize_money(metric.amount)} × {rule.rate} = {amount}; "
            f"rule {rule.rule_id} version {rule.version}."
        ),
    )
    return FiscalCalculationResult(applicability=applicability, obligation=obligation)


def reconcile_fiscal_obligation(
    obligation: FiscalObligation,
    events: tuple[FinancialEvent, ...],
) -> ReconciliationResult:
    matching = tuple(
        event
        for event in events
        if event.obligation_key == obligation.obligation_key
        and event.status is not FinancialEventStatus.CANCELLED
    )
    if not matching:
        return ReconciliationResult(
            action=ReconciliationAction.ADD_OBLIGATION,
            obligation=obligation,
            matching_event_ids=(),
            outstanding_amount=obligation.amount,
            forecast_due_date=obligation.due_date,
        )

    paid_amount = normalize_money(sum(
        (event.settled_amount for event in matching),
        start=Decimal("0.00"),
    ))
    if all(event.status is FinancialEventStatus.SETTLED for event in matching):
        paid_amount = max(paid_amount, obligation.amount)
    outstanding = normalize_money(max(obligation.amount - paid_amount, Decimal("0.00")))
    action = (
        ReconciliationAction.ALREADY_SETTLED
        if outstanding == Decimal("0.00")
        else ReconciliationAction.USE_EXISTING
    )
    return ReconciliationResult(
        action=action,
        obligation=obligation,
        matching_event_ids=tuple(event.external_id for event in matching),
        outstanding_amount=outstanding,
        forecast_due_date=min(event.due_date for event in matching),
    )


def _latest_metric(
    metrics: tuple[AccountingMetric, ...],
    code: str,
    as_of: date,
) -> AccountingMetric | None:
    candidates = [
        metric for metric in metrics if metric.code == code and metric.period_end <= as_of
    ]
    return max(candidates, key=lambda metric: metric.period_end, default=None)
