from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from enum import Enum

from finradar.domain.fiscal import FiscalObligation, FiscalRuleStatus
from finradar.domain.financial_snapshot import FinancialEvent, FinancialEventStatus
from finradar.domain.forecast import normalize_money


class ConsequenceStatus(str, Enum):
    ACCRUED = "accrued"
    CALCULATED = "calculated"
    CONTINGENT = "contingent"
    UNRESOLVED = "unresolved"


class ViolationType(str, Enum):
    LATE_PAYMENT = "late_payment"
    MISSING_DECLARATION = "missing_declaration"
    UNDERSTATEMENT = "understatement"


@dataclass(frozen=True, slots=True)
class PenaltyRatePeriod:
    effective_from: date
    effective_to: date | None
    daily_rate: Decimal


@dataclass(frozen=True, slots=True)
class LatePaymentPenaltyRule:
    rule_id: str
    version: int
    applies_to_obligation_rule_id: str
    grace_days: int
    rate_periods: tuple[PenaltyRatePeriod, ...]
    source_reference: str
    status: FiscalRuleStatus = FiscalRuleStatus.CANDIDATE


@dataclass(frozen=True, slots=True)
class FineRule:
    rule_id: str
    version: int
    violation_type: ViolationType
    applies_to_obligation_rule_ids: frozenset[str]
    fixed_amount: Decimal | None
    percentage_of_outstanding: Decimal | None
    minimum_amount: Decimal | None
    maximum_amount: Decimal | None
    requires_authority_decision: bool
    source_reference: str
    status: FiscalRuleStatus = FiscalRuleStatus.CANDIDATE


@dataclass(frozen=True, slots=True)
class ViolationEvent:
    violation_id: str
    violation_type: ViolationType
    obligation_key: str
    occurred_on: date
    confirmed: bool
    authority_decision_id: str | None = None


@dataclass(frozen=True, slots=True)
class PenaltySegment:
    start_date: date
    end_date: date
    days: int
    daily_rate: Decimal
    amount: Decimal


@dataclass(frozen=True, slots=True)
class FiscalConsequence:
    consequence_key: str
    consequence_type: str
    status: ConsequenceStatus
    related_obligation_key: str
    amount: Decimal | None
    currency: str
    assessment_date: date
    source_reference: str
    explanation: str
    segments: tuple[PenaltySegment, ...] = ()
    missing_fields: tuple[str, ...] = ()


def calculate_late_payment_penalty(
    rule: LatePaymentPenaltyRule,
    obligation: FiscalObligation,
    *,
    outstanding_amount: Decimal,
    overdue_through: date,
    status: ConsequenceStatus,
) -> FiscalConsequence | None:
    if rule.status is not FiscalRuleStatus.ACTIVE:
        return None
    if rule.applies_to_obligation_rule_id != obligation.rule_id:
        return None
    if status not in {ConsequenceStatus.CALCULATED, ConsequenceStatus.CONTINGENT}:
        raise ValueError("Penalty calculation requires calculated or contingent status.")
    if rule.grace_days < 0:
        raise ValueError("Penalty grace period cannot be negative.")

    principal = normalize_money(max(outstanding_amount, Decimal("0.00")))
    accrual_start = obligation.due_date + timedelta(days=rule.grace_days + 1)
    if principal == Decimal("0.00") or overdue_through < accrual_start:
        return None

    segments, missing_dates = _build_penalty_segments(
        rule.rate_periods,
        principal=principal,
        start_date=accrual_start,
        end_date=overdue_through,
    )
    consequence_key = (
        f"penalty:{obligation.obligation_key}:"
        f"{accrual_start.isoformat()}:{overdue_through.isoformat()}"
    )
    if missing_dates:
        return FiscalConsequence(
            consequence_key=consequence_key,
            consequence_type="late_payment_penalty",
            status=ConsequenceStatus.UNRESOLVED,
            related_obligation_key=obligation.obligation_key,
            amount=None,
            currency=obligation.currency,
            assessment_date=overdue_through,
            source_reference=rule.source_reference,
            explanation="Penalty cannot be calculated because rate coverage is incomplete.",
            missing_fields=tuple(
                f"penalty_rate:{item.isoformat()}" for item in missing_dates
            ),
        )

    amount = normalize_money(sum((segment.amount for segment in segments), Decimal("0.00")))
    return FiscalConsequence(
        consequence_key=consequence_key,
        consequence_type="late_payment_penalty",
        status=status,
        related_obligation_key=obligation.obligation_key,
        amount=amount,
        currency=obligation.currency,
        assessment_date=overdue_through,
        source_reference=rule.source_reference,
        explanation=(
            f"Penalty on {principal} for {sum(segment.days for segment in segments)} "
            f"overdue day(s) equals {amount}."
        ),
        segments=segments,
    )


def calculate_fine(
    rule: FineRule,
    violation: ViolationEvent,
    obligation: FiscalObligation,
    *,
    outstanding_amount: Decimal,
) -> FiscalConsequence | None:
    if rule.status is not FiscalRuleStatus.ACTIVE:
        return None
    if rule.violation_type is not violation.violation_type:
        return None
    if obligation.rule_id not in rule.applies_to_obligation_rule_ids:
        return None

    amount = _calculate_fine_amount(rule, outstanding_amount)
    if amount is None:
        return FiscalConsequence(
            consequence_key=f"fine:{rule.rule_id}:{violation.violation_id}",
            consequence_type="fine",
            status=ConsequenceStatus.UNRESOLVED,
            related_obligation_key=obligation.obligation_key,
            amount=None,
            currency=obligation.currency,
            assessment_date=violation.occurred_on,
            source_reference=rule.source_reference,
            explanation="Fine formula is incomplete or ambiguous.",
            missing_fields=("fine_formula",),
        )

    is_final = violation.confirmed and (
        not rule.requires_authority_decision
        or violation.authority_decision_id is not None
    )
    status = ConsequenceStatus.CALCULATED if is_final else ConsequenceStatus.CONTINGENT
    return FiscalConsequence(
        consequence_key=f"fine:{rule.rule_id}:{violation.violation_id}",
        consequence_type="fine",
        status=status,
        related_obligation_key=obligation.obligation_key,
        amount=amount,
        currency=obligation.currency,
        assessment_date=violation.occurred_on,
        source_reference=rule.source_reference,
        explanation=(
            f"Formalized fine estimate equals {amount}. "
            f"Authority decision required: {rule.requires_authority_decision}."
        ),
    )


def accrued_consequence_from_event(
    event: FinancialEvent,
) -> FiscalConsequence | None:
    if (
        event.fiscal_consequence_type is None
        or event.related_obligation_key is None
        or event.obligation_key is None
        or event.status is FinancialEventStatus.CANCELLED
    ):
        return None
    outstanding = normalize_money(
        max(event.amount - event.settled_amount, Decimal("0.00"))
    )
    return FiscalConsequence(
        consequence_key=event.obligation_key,
        consequence_type=event.fiscal_consequence_type,
        status=ConsequenceStatus.ACCRUED,
        related_obligation_key=event.related_obligation_key,
        amount=outstanding,
        currency=event.currency,
        assessment_date=event.due_date,
        source_reference=event.external_id,
        explanation="Charge was supplied by the accounting source.",
    )


def _build_penalty_segments(
    periods: tuple[PenaltyRatePeriod, ...],
    *,
    principal: Decimal,
    start_date: date,
    end_date: date,
) -> tuple[tuple[PenaltySegment, ...], tuple[date, ...]]:
    segments: list[PenaltySegment] = []
    covered_dates: set[date] = set()
    overlapping_dates: set[date] = set()

    for period in sorted(periods, key=lambda item: item.effective_from):
        period_end = period.effective_to or end_date
        segment_start = max(start_date, period.effective_from)
        segment_end = min(end_date, period_end)
        if segment_start > segment_end:
            continue
        days = (segment_end - segment_start).days + 1
        dates = {segment_start + timedelta(days=offset) for offset in range(days)}
        if period.daily_rate < Decimal("0.00"):
            overlapping_dates.update(dates)
        overlapping_dates.update(covered_dates & dates)
        covered_dates.update(dates)
        segments.append(
            PenaltySegment(
                start_date=segment_start,
                end_date=segment_end,
                days=days,
                daily_rate=period.daily_rate,
                amount=normalize_money(principal * period.daily_rate * days),
            )
        )

    expected_dates = {
        start_date + timedelta(days=offset)
        for offset in range((end_date - start_date).days + 1)
    }
    invalid_dates = tuple(sorted((expected_dates - covered_dates) | overlapping_dates))
    return tuple(segments), invalid_dates


def _calculate_fine_amount(rule: FineRule, outstanding_amount: Decimal) -> Decimal | None:
    configured = sum(
        value is not None
        for value in (rule.fixed_amount, rule.percentage_of_outstanding)
    )
    if configured != 1:
        return None
    if (
        (rule.fixed_amount is not None and rule.fixed_amount < Decimal("0.00"))
        or (
            rule.percentage_of_outstanding is not None
            and rule.percentage_of_outstanding < Decimal("0.00")
        )
        or (
            rule.minimum_amount is not None
            and rule.maximum_amount is not None
            and rule.minimum_amount > rule.maximum_amount
        )
    ):
        return None

    if rule.fixed_amount is not None:
        amount = rule.fixed_amount
    else:
        assert rule.percentage_of_outstanding is not None
        amount = outstanding_amount * rule.percentage_of_outstanding

    if rule.minimum_amount is not None:
        amount = max(amount, rule.minimum_amount)
    if rule.maximum_amount is not None:
        amount = min(amount, rule.maximum_amount)
    return normalize_money(max(amount, Decimal("0.00")))
