from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from finradar.application.analytical_service import analyze_financial_risk
from finradar.domain.financial_snapshot import (
    AccountBalance,
    AccountingMetric,
    CompanyProfile,
    DatasetKind,
    FinancialDirection,
    FinancialEvent,
    FinancialEventKind,
    FinancialEventStatus,
    FinancialSnapshot,
)
from finradar.domain.fiscal import (
    ApplicabilityStatus,
    FiscalRuleStatus,
    PercentageFiscalRule,
    ReconciliationAction,
)
from finradar.domain.fiscal_consequences import (
    ConsequenceStatus,
    FineRule,
    LatePaymentPenaltyRule,
    PenaltyRatePeriod,
    ViolationEvent,
    ViolationType,
)


AS_OF = date(2026, 7, 19)
PERIOD_START = date(2026, 6, 1)
PERIOD_END = date(2026, 7, 18)
OBLIGATION_KEY = "fictional-turnover:2026-06-01:2026-07-18"


def make_rule(**changes) -> PercentageFiscalRule:
    rule = PercentageFiscalRule(
        rule_id="fictional-turnover",
        version=1,
        title="Fictional turnover obligation",
        jurisdiction="XX",
        tax_regimes=frozenset({"fictional-standard"}),
        effective_from=date(2026, 1, 1),
        effective_to=None,
        base_metric_code="fictional_taxable_revenue",
        rate=Decimal("0.10"),
        payment_days_after_period_end=3,
        obligation_category="fictional_tax",
        source_reference="fictional-rulebook/article-1",
        status=FiscalRuleStatus.ACTIVE,
    )
    return replace(rule, **changes)


def make_snapshot(
    *,
    events: tuple[FinancialEvent, ...] = (),
    include_metric: bool = True,
    tax_regime: str | None = "fictional-standard",
) -> FinancialSnapshot:
    return FinancialSnapshot(
        source_system="fictional-accounting",
        captured_at=datetime(2026, 7, 19, tzinfo=timezone.utc),
        available_datasets=frozenset(DatasetKind),
        company=CompanyProfile(
            external_id="company-1",
            name="Fictional Company",
            base_currency="GEL",
            jurisdiction="XX",
            tax_regime=tax_regime,
        ),
        balances=(
            AccountBalance(
                external_id="account-1",
                name="Main",
                currency="GEL",
                amount=Decimal("50.00"),
                balance_date=AS_OF,
            ),
        ),
        metrics=(
            AccountingMetric(
                code="fictional_taxable_revenue",
                amount=Decimal("1000.00"),
                currency="GEL",
                period_start=PERIOD_START,
                period_end=PERIOD_END,
                source_reference="fictional-ledger",
            ),
        )
        if include_metric
        else (),
        events=events,
    )


def make_existing_obligation(
    *,
    status: FinancialEventStatus,
    settled_amount: str = "0.00",
) -> FinancialEvent:
    return FinancialEvent(
        external_id="existing-obligation",
        title="Existing fictional obligation",
        amount=Decimal("100.00"),
        currency="GEL",
        due_date=PERIOD_END + timedelta(days=3),
        direction=FinancialDirection.OUTFLOW,
        kind=(
            FinancialEventKind.FACT
            if status is FinancialEventStatus.SETTLED
            else FinancialEventKind.PLANNED
        ),
        status=status,
        settled_amount=Decimal(settled_amount),
        obligation_key=OBLIGATION_KEY,
        category="fictional_tax",
    )


def test_applicable_rule_adds_obligation_and_changes_cash_gap() -> None:
    result = analyze_financial_risk(
        make_snapshot(),
        (make_rule(),),
        as_of=AS_OF,
        horizon_days=10,
    )

    analysis = result.rule_analyses[0]
    assert analysis.calculation.applicability.status is ApplicabilityStatus.APPLIED
    assert analysis.calculation.obligation is not None
    assert analysis.calculation.obligation.amount == Decimal("100.00")
    assert analysis.reconciliation is not None
    assert analysis.reconciliation.action is ReconciliationAction.ADD_OBLIGATION
    assert result.forecast.first_gap_date == date(2026, 7, 21)
    assert result.forecast.required_funding == Decimal("50.00")


def test_non_matching_jurisdiction_does_not_add_obligation() -> None:
    result = analyze_financial_risk(
        make_snapshot(),
        (make_rule(jurisdiction="YY"),),
        as_of=AS_OF,
        horizon_days=10,
    )

    analysis = result.rule_analyses[0]
    assert analysis.calculation.applicability.status is ApplicabilityStatus.NOT_APPLICABLE
    assert analysis.reconciliation is None
    assert result.forecast_events == ()


def test_missing_tax_regime_is_unresolved() -> None:
    result = analyze_financial_risk(
        make_snapshot(tax_regime=None),
        (make_rule(),),
        as_of=AS_OF,
        horizon_days=10,
    )

    applicability = result.rule_analyses[0].calculation.applicability
    assert applicability.status is ApplicabilityStatus.UNRESOLVED
    assert applicability.missing_fields == ("company.tax_regime",)


def test_missing_tax_base_is_unresolved() -> None:
    result = analyze_financial_risk(
        make_snapshot(include_metric=False),
        (make_rule(),),
        as_of=AS_OF,
        horizon_days=10,
    )

    applicability = result.rule_analyses[0].calculation.applicability
    assert applicability.status is ApplicabilityStatus.UNRESOLVED
    assert applicability.missing_fields == (
        "accounting_metric:fictional_taxable_revenue",
    )


def test_existing_calendar_obligation_is_not_duplicated() -> None:
    snapshot = make_snapshot(
        events=(
            make_existing_obligation(status=FinancialEventStatus.CONFIRMED),
        )
    )

    result = analyze_financial_risk(
        snapshot,
        (make_rule(),),
        as_of=AS_OF,
        horizon_days=10,
    )

    reconciliation = result.rule_analyses[0].reconciliation
    assert reconciliation is not None
    assert reconciliation.action is ReconciliationAction.USE_EXISTING
    assert len(result.forecast_events) == 1
    assert result.forecast_events[0].amount == Decimal("100.00")


def test_duplicate_calendar_rows_with_same_obligation_key_are_consolidated() -> None:
    first = make_existing_obligation(status=FinancialEventStatus.CONFIRMED)
    second = replace(first, external_id="duplicate-obligation")
    snapshot = make_snapshot(events=(first, second))

    result = analyze_financial_risk(
        snapshot,
        (make_rule(),),
        as_of=AS_OF,
        horizon_days=10,
    )

    reconciliation = result.rule_analyses[0].reconciliation
    assert reconciliation is not None
    assert reconciliation.matching_event_ids == (
        "existing-obligation",
        "duplicate-obligation",
    )
    assert len(result.forecast_events) == 1
    assert result.forecast_events[0].amount == Decimal("100.00")


def test_settled_obligation_is_not_forecast_again() -> None:
    snapshot = make_snapshot(
        events=(make_existing_obligation(status=FinancialEventStatus.SETTLED),)
    )

    result = analyze_financial_risk(
        snapshot,
        (make_rule(),),
        as_of=AS_OF,
        horizon_days=10,
    )

    reconciliation = result.rule_analyses[0].reconciliation
    assert reconciliation is not None
    assert reconciliation.action is ReconciliationAction.ALREADY_SETTLED
    assert result.forecast_events == ()


def test_partial_payment_leaves_only_unpaid_amount_in_forecast() -> None:
    snapshot = make_snapshot(
        events=(
            make_existing_obligation(
                status=FinancialEventStatus.CONFIRMED,
                settled_amount="30.00",
            ),
        )
    )

    result = analyze_financial_risk(
        snapshot,
        (make_rule(),),
        as_of=AS_OF,
        horizon_days=10,
    )

    reconciliation = result.rule_analyses[0].reconciliation
    assert reconciliation is not None
    assert reconciliation.outstanding_amount == Decimal("70.00")
    assert result.forecast_events[0].amount == Decimal("70.00")


def test_superseded_and_expired_rules_are_not_applied() -> None:
    rules = (
        make_rule(status=FiscalRuleStatus.SUPERSEDED),
        make_rule(rule_id="expired", effective_to=AS_OF - timedelta(days=1)),
    )

    result = analyze_financial_risk(
        make_snapshot(),
        rules,
        as_of=AS_OF,
        horizon_days=10,
    )

    assert all(
        item.calculation.applicability.status is ApplicabilityStatus.NOT_APPLICABLE
        for item in result.rule_analyses
    )
    assert result.forecast_events == ()


def test_rule_rate_change_changes_result_deterministically() -> None:
    snapshot = make_snapshot()

    first = analyze_financial_risk(
        snapshot,
        (make_rule(rate=Decimal("0.10")),),
        as_of=AS_OF,
        horizon_days=10,
    )
    second = analyze_financial_risk(
        snapshot,
        (make_rule(version=2, rate=Decimal("0.20")),),
        as_of=AS_OF,
        horizon_days=10,
    )

    assert first.rule_analyses[0].calculation.obligation is not None
    assert second.rule_analyses[0].calculation.obligation is not None
    assert first.rule_analyses[0].calculation.obligation.amount == Decimal("100.00")
    assert second.rule_analyses[0].calculation.obligation.amount == Decimal("200.00")
    assert (
        first.rule_analyses[0].calculation.obligation.obligation_key
        == second.rule_analyses[0].calculation.obligation.obligation_key
    )


def make_penalty_rule() -> LatePaymentPenaltyRule:
    return LatePaymentPenaltyRule(
        rule_id="fictional-late-penalty",
        version=1,
        applies_to_obligation_rule_id="fictional-turnover",
        grace_days=0,
        rate_periods=(
            PenaltyRatePeriod(
                effective_from=date(2026, 1, 1),
                effective_to=None,
                daily_rate=Decimal("0.01"),
            ),
        ),
        source_reference="fictional-penalty-source",
        status=FiscalRuleStatus.ACTIVE,
    )


def test_future_penalty_is_only_in_stress_forecast() -> None:
    result = analyze_financial_risk(
        make_snapshot(),
        (make_rule(),),
        as_of=AS_OF,
        horizon_days=10,
        penalty_rules=(make_penalty_rule(),),
        stress_overdue_days=5,
    )

    assert len(result.consequences) == 1
    consequence = result.consequences[0]
    assert consequence.status is ConsequenceStatus.CONTINGENT
    assert consequence.amount == Decimal("5.00")
    assert result.forecast.minimum_balance == Decimal("-50.00")
    assert result.stress_forecast.minimum_balance == Decimal("-55.00")


def test_actual_overdue_principal_and_penalty_enter_base_forecast() -> None:
    later_date = date(2026, 7, 25)
    result = analyze_financial_risk(
        make_snapshot(),
        (make_rule(),),
        as_of=later_date,
        horizon_days=10,
        penalty_rules=(make_penalty_rule(),),
    )

    assert len(result.consequences) == 1
    consequence = result.consequences[0]
    assert consequence.status is ConsequenceStatus.CALCULATED
    assert consequence.amount == Decimal("4.00")
    assert result.forecast.points[0].outflow == Decimal("104.00")


def test_contingent_fine_does_not_enter_base_forecast() -> None:
    fine_rule = FineRule(
        rule_id="fictional-fine",
        version=1,
        violation_type=ViolationType.LATE_PAYMENT,
        applies_to_obligation_rule_ids=frozenset({"fictional-turnover"}),
        fixed_amount=Decimal("25.00"),
        percentage_of_outstanding=None,
        minimum_amount=None,
        maximum_amount=None,
        requires_authority_decision=True,
        source_reference="fictional-fine-source",
        status=FiscalRuleStatus.ACTIVE,
    )
    violation = ViolationEvent(
        violation_id="violation-1",
        violation_type=ViolationType.LATE_PAYMENT,
        obligation_key=OBLIGATION_KEY,
        occurred_on=date(2026, 7, 21),
        confirmed=True,
    )

    result = analyze_financial_risk(
        make_snapshot(),
        (make_rule(),),
        as_of=AS_OF,
        horizon_days=10,
        fine_rules=(fine_rule,),
        violation_events=(violation,),
    )

    assert result.consequences[0].status is ConsequenceStatus.CONTINGENT
    assert result.forecast.minimum_balance == Decimal("-50.00")
    assert result.stress_forecast.minimum_balance == Decimal("-75.00")


def test_accounting_charge_is_reported_as_accrued_without_duplication() -> None:
    accrued_penalty = FinancialEvent(
        external_id="accounting-penalty-1",
        title="Accrued fictional penalty",
        amount=Decimal("12.00"),
        currency="GEL",
        due_date=date(2026, 7, 22),
        direction=FinancialDirection.OUTFLOW,
        kind=FinancialEventKind.PLANNED,
        status=FinancialEventStatus.CONFIRMED,
        obligation_key="penalty-record-1",
        related_obligation_key=OBLIGATION_KEY,
        fiscal_consequence_type="late_payment_penalty",
    )

    result = analyze_financial_risk(
        make_snapshot(events=(accrued_penalty,)),
        (make_rule(),),
        as_of=AS_OF,
        horizon_days=10,
    )

    accrued = [
        item for item in result.consequences if item.status is ConsequenceStatus.ACCRUED
    ]
    assert len(accrued) == 1
    assert accrued[0].amount == Decimal("12.00")
    assert sum(
        event.amount
        for event in result.forecast_events
        if event.reference == "accounting-penalty-1"
    ) == Decimal("12.00")
