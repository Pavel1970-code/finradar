from datetime import date
from decimal import Decimal

from finradar.application.synchronization_service import synchronize_and_forecast
from finradar.domain.data_readiness import ReadinessStatus
from finradar.domain.financial_snapshot import DatasetKind
from finradar.domain.fiscal import FiscalRuleStatus, PercentageFiscalRule
from finradar.domain.fiscal_consequences import (
    ConsequenceStatus,
    LatePaymentPenaltyRule,
    PenaltyRatePeriod,
)
from finradar.infrastructure.connectors.demo import DemoAccountingConnector


AS_OF = date(2026, 7, 18)


def test_complete_demo_synchronization_builds_forecast() -> None:
    outcome = synchronize_and_forecast(
        DemoAccountingConnector(as_of=AS_OF),
        as_of=AS_OF,
    )

    assert outcome.readiness.status is ReadinessStatus.READY
    assert outcome.forecast is not None
    assert outcome.forecast.first_gap_date == date(2026, 7, 20)
    assert outcome.forecast.minimum_balance == Decimal("-500.00")
    assert outcome.forecast.required_funding == Decimal("500.00")


def test_missing_payment_calendar_returns_limited_zero_event_forecast() -> None:
    connector = DemoAccountingConnector(
        as_of=AS_OF,
        unavailable_datasets=frozenset({DatasetKind.PAYMENT_CALENDAR}),
    )

    outcome = synchronize_and_forecast(connector, as_of=AS_OF)

    assert outcome.readiness.status is ReadinessStatus.LIMITED
    assert outcome.forecast is not None
    assert outcome.forecast.closing_balance == Decimal("1000.00")
    assert {issue.code for issue in outcome.readiness.issues} == {
        "payment_calendar_unavailable"
    }


def test_missing_balances_blocks_forecast() -> None:
    connector = DemoAccountingConnector(
        as_of=AS_OF,
        unavailable_datasets=frozenset({DatasetKind.ACCOUNT_BALANCES}),
    )

    outcome = synchronize_and_forecast(connector, as_of=AS_OF)

    assert outcome.readiness.status is ReadinessStatus.BLOCKED
    assert outcome.forecast is None


def test_synchronization_can_apply_active_fiscal_rule_to_connector_facts() -> None:
    rule = PercentageFiscalRule(
        rule_id="fictional-demo-tax",
        version=1,
        title="Fictional demo obligation",
        jurisdiction="GE",
        tax_regimes=frozenset({"fictional-demo-regime"}),
        effective_from=date(2026, 1, 1),
        effective_to=None,
        base_metric_code="fictional_taxable_revenue",
        rate=Decimal("0.10"),
        payment_days_after_period_end=3,
        obligation_category="fictional_tax",
        source_reference="fictional-source",
        status=FiscalRuleStatus.ACTIVE,
    )

    outcome = synchronize_and_forecast(
        DemoAccountingConnector(as_of=AS_OF),
        as_of=AS_OF,
        fiscal_rules=(rule,),
    )

    assert outcome.forecast is not None
    assert len(outcome.rule_analyses) == 1
    obligation = outcome.rule_analyses[0].calculation.obligation
    assert obligation is not None
    assert obligation.amount == Decimal("1000.00")


def test_synchronization_exposes_contingent_penalty_and_stress_forecast() -> None:
    fiscal_rule = PercentageFiscalRule(
        rule_id="fictional-demo-tax",
        version=1,
        title="Fictional demo obligation",
        jurisdiction="GE",
        tax_regimes=frozenset({"fictional-demo-regime"}),
        effective_from=date(2026, 1, 1),
        effective_to=None,
        base_metric_code="fictional_taxable_revenue",
        rate=Decimal("0.10"),
        payment_days_after_period_end=3,
        obligation_category="fictional_tax",
        source_reference="fictional-source",
        status=FiscalRuleStatus.ACTIVE,
    )
    penalty_rule = LatePaymentPenaltyRule(
        rule_id="fictional-demo-penalty",
        version=1,
        applies_to_obligation_rule_id="fictional-demo-tax",
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

    outcome = synchronize_and_forecast(
        DemoAccountingConnector(as_of=AS_OF),
        as_of=AS_OF,
        fiscal_rules=(fiscal_rule,),
        penalty_rules=(penalty_rule,),
        stress_overdue_days=5,
    )

    assert outcome.stress_forecast is not None
    assert len(outcome.consequences) == 1
    assert outcome.consequences[0].status is ConsequenceStatus.CONTINGENT
    assert outcome.stress_forecast.minimum_balance < outcome.forecast.minimum_balance
