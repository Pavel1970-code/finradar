from dataclasses import replace
from datetime import date
from decimal import Decimal

from finradar.domain.fiscal import FiscalObligation, FiscalRuleStatus
from finradar.domain.fiscal_consequences import (
    ConsequenceStatus,
    FineRule,
    LatePaymentPenaltyRule,
    PenaltyRatePeriod,
    ViolationEvent,
    ViolationType,
    calculate_fine,
    calculate_late_payment_penalty,
)


def make_obligation() -> FiscalObligation:
    return FiscalObligation(
        obligation_key="fictional-tax:2026-06-01:2026-06-30",
        rule_id="fictional-tax",
        rule_version=1,
        title="Fictional obligation",
        amount=Decimal("1000.00"),
        currency="GEL",
        due_date=date(2026, 7, 10),
        category="fictional_tax",
        base_amount=Decimal("10000.00"),
        rate=Decimal("0.10"),
        source_reference="fictional-source",
        explanation="Fictional calculation.",
    )


def make_penalty_rule(**changes) -> LatePaymentPenaltyRule:
    rule = LatePaymentPenaltyRule(
        rule_id="fictional-penalty",
        version=1,
        applies_to_obligation_rule_id="fictional-tax",
        grace_days=0,
        rate_periods=(
            PenaltyRatePeriod(
                effective_from=date(2026, 1, 1),
                effective_to=None,
                daily_rate=Decimal("0.001"),
            ),
        ),
        source_reference="fictional-penalty-source",
        status=FiscalRuleStatus.ACTIVE,
    )
    return replace(rule, **changes)


def test_penalty_counts_each_overdue_day_after_due_date() -> None:
    consequence = calculate_late_payment_penalty(
        make_penalty_rule(),
        make_obligation(),
        outstanding_amount=Decimal("1000.00"),
        overdue_through=date(2026, 7, 15),
        status=ConsequenceStatus.CALCULATED,
    )

    assert consequence is not None
    assert consequence.status is ConsequenceStatus.CALCULATED
    assert consequence.amount == Decimal("5.00")
    assert consequence.segments[0].days == 5


def test_penalty_splits_changed_rates_without_losing_days() -> None:
    rule = make_penalty_rule(
        rate_periods=(
            PenaltyRatePeriod(
                effective_from=date(2026, 1, 1),
                effective_to=date(2026, 7, 12),
                daily_rate=Decimal("0.001"),
            ),
            PenaltyRatePeriod(
                effective_from=date(2026, 7, 13),
                effective_to=None,
                daily_rate=Decimal("0.002"),
            ),
        )
    )

    consequence = calculate_late_payment_penalty(
        rule,
        make_obligation(),
        outstanding_amount=Decimal("1000.00"),
        overdue_through=date(2026, 7, 15),
        status=ConsequenceStatus.CALCULATED,
    )

    assert consequence is not None
    assert consequence.amount == Decimal("8.00")
    assert [segment.days for segment in consequence.segments] == [2, 3]


def test_missing_rate_day_makes_penalty_unresolved() -> None:
    rule = make_penalty_rule(
        rate_periods=(
            PenaltyRatePeriod(
                effective_from=date(2026, 7, 12),
                effective_to=None,
                daily_rate=Decimal("0.001"),
            ),
        )
    )

    consequence = calculate_late_payment_penalty(
        rule,
        make_obligation(),
        outstanding_amount=Decimal("1000.00"),
        overdue_through=date(2026, 7, 13),
        status=ConsequenceStatus.CALCULATED,
    )

    assert consequence is not None
    assert consequence.status is ConsequenceStatus.UNRESOLVED
    assert consequence.amount is None
    assert consequence.missing_fields == ("penalty_rate:2026-07-11",)


def test_fine_requiring_decision_remains_contingent_without_decision() -> None:
    rule = FineRule(
        rule_id="fictional-fine",
        version=1,
        violation_type=ViolationType.LATE_PAYMENT,
        applies_to_obligation_rule_ids=frozenset({"fictional-tax"}),
        fixed_amount=None,
        percentage_of_outstanding=Decimal("0.20"),
        minimum_amount=Decimal("50.00"),
        maximum_amount=Decimal("500.00"),
        requires_authority_decision=True,
        source_reference="fictional-fine-source",
        status=FiscalRuleStatus.ACTIVE,
    )
    violation = ViolationEvent(
        violation_id="violation-1",
        violation_type=ViolationType.LATE_PAYMENT,
        obligation_key=make_obligation().obligation_key,
        occurred_on=date(2026, 7, 11),
        confirmed=True,
    )

    contingent = calculate_fine(
        rule,
        violation,
        make_obligation(),
        outstanding_amount=Decimal("1000.00"),
    )
    calculated = calculate_fine(
        rule,
        replace(violation, authority_decision_id="decision-1"),
        make_obligation(),
        outstanding_amount=Decimal("1000.00"),
    )

    assert contingent is not None
    assert calculated is not None
    assert contingent.status is ConsequenceStatus.CONTINGENT
    assert calculated.status is ConsequenceStatus.CALCULATED
    assert calculated.amount == Decimal("200.00")
