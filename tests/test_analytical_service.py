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
