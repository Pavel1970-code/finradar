from dataclasses import replace
from datetime import date
from decimal import Decimal

from finradar.application.analytical_service import analyze_financial_risk
from finradar.application.forecast_facade import (
    ForecastApplicationFacade,
    ForecastRunConfiguration,
)
from finradar.demo.scenario import DemoScenarioRepository
from finradar.domain.fiscal import (
    ApplicabilityStatus,
    FiscalPositionType,
    FiscalRuleStatus,
    GeorgianVatRule,
    calculate_fiscal_obligation,
)
from finradar.infrastructure.connectors.scenario import ScenarioAccountingConnector
from finradar.infrastructure.fiscal_rule_codec import decode_rule, encode_rule
from finradar.ui.forecast_view_model import build_forecast_view_model


def _scenario():
    return DemoScenarioRepository().load("georgia_vat_pilot")


def _rule() -> GeorgianVatRule:
    rule = _scenario().fiscal_rules.obligation_rules[0]
    assert isinstance(rule, GeorgianVatRule)
    return rule


def test_georgian_vat_builds_auditable_net_position_and_cash_forecast() -> None:
    scenario = _scenario()
    result = analyze_financial_risk(
        scenario.accounting_snapshot,
        scenario.fiscal_rules.obligation_rules,
        as_of=scenario.as_of,
        horizon_days=scenario.horizon_days,
    )

    analysis = result.rule_analyses[0]
    calculation = analysis.calculation
    assert calculation.applicability.status is ApplicabilityStatus.APPLIED
    assert calculation.position is FiscalPositionType.PAYABLE
    assert calculation.net_amount == Decimal("2500.00")
    assert tuple(item.amount for item in calculation.components) == (
        Decimal("3600.00"),
        Decimal("-1100.00"),
        Decimal("0.00"),
        Decimal("0.00"),
        Decimal("0.00"),
    )
    assert calculation.obligation is not None
    assert calculation.obligation.due_date == date(2026, 7, 15)
    assert analysis.reconciliation is not None
    assert analysis.reconciliation.outstanding_amount == Decimal("2000.00")
    assert result.forecast.minimum_balance == Decimal("-3000.00")


def test_missing_vat_component_is_reported_and_not_assumed_to_be_zero() -> None:
    scenario = _scenario()
    snapshot = replace(
        scenario.accounting_snapshot,
        metrics=tuple(
            item
            for item in scenario.accounting_snapshot.metrics
            if item.code != "ge_vat_import_vat_payable"
        ),
    )

    calculation = calculate_fiscal_obligation(
        _rule(),
        snapshot,
        as_of=scenario.as_of,
    )

    assert calculation.applicability.status is ApplicabilityStatus.UNRESOLVED
    assert calculation.obligation is None
    assert calculation.applicability.missing_fields == (
        "accounting_metric:ge_vat_import_vat_payable",
    )


def test_unsupported_mixed_or_exempt_activity_stops_narrow_vat_model() -> None:
    scenario = _scenario()
    snapshot = replace(
        scenario.accounting_snapshot,
        metrics=tuple(
            replace(item, amount=Decimal("100.00"))
            if item.code == "ge_vat_exempt_or_mixed_use_turnover"
            else item
            for item in scenario.accounting_snapshot.metrics
        ),
    )

    calculation = calculate_fiscal_obligation(
        _rule(),
        snapshot,
        as_of=scenario.as_of,
    )

    assert calculation.applicability.status is ApplicabilityStatus.UNRESOLVED
    assert calculation.applicability.missing_fields == (
        "supported_scope:ge_vat_exempt_or_mixed_use_turnover",
    )


def test_vat_credit_is_exposed_but_not_added_as_cash_inflow() -> None:
    scenario = _scenario()
    snapshot = replace(
        scenario.accounting_snapshot,
        metrics=tuple(
            replace(item, amount=Decimal("5000.00"))
            if item.code == "ge_vat_deductible_input_vat"
            else item
            for item in scenario.accounting_snapshot.metrics
        ),
        events=(),
    )

    result = analyze_financial_risk(
        snapshot,
        (_rule(),),
        as_of=scenario.as_of,
        horizon_days=scenario.horizon_days,
    )
    calculation = result.rule_analyses[0].calculation

    assert calculation.position is FiscalPositionType.CREDIT
    assert calculation.net_amount == Decimal("-1400.00")
    assert calculation.obligation is None
    assert result.forecast_events == ()


def test_following_month_deadline_rolls_over_a_weekend() -> None:
    scenario = _scenario()
    snapshot = replace(
        scenario.accounting_snapshot,
        metrics=tuple(
            replace(
                item,
                period_start=date(2026, 7, 1),
                period_end=date(2026, 7, 31),
            )
            for item in scenario.accounting_snapshot.metrics
        ),
        events=(),
    )

    calculation = calculate_fiscal_obligation(
        _rule(),
        snapshot,
        as_of=date(2026, 8, 1),
    )

    assert calculation.obligation is not None
    assert calculation.obligation.due_date == date(2026, 8, 17)


def test_georgian_vat_rule_codec_round_trip_preserves_scope_contract() -> None:
    rule_type, content = encode_rule(
        replace(_rule(), status=FiscalRuleStatus.CANDIDATE)
    )

    restored = decode_rule(content, status=FiscalRuleStatus.ACTIVE)

    assert rule_type == "georgian_vat"
    assert isinstance(restored, GeorgianVatRule)
    assert restored.rate == Decimal("0.18")
    assert (
        restored.excluded_or_mixed_use_metric_code
        == "ge_vat_exempt_or_mixed_use_turnover"
    )


def test_unresolved_vat_inputs_are_visible_in_user_report() -> None:
    scenario = _scenario()
    snapshot = replace(
        scenario.accounting_snapshot,
        metrics=tuple(
            item
            for item in scenario.accounting_snapshot.metrics
            if item.code != "ge_vat_reverse_charge_vat_payable"
        ),
    )
    facade = ForecastApplicationFacade(
        ScenarioAccountingConnector(replace(scenario, accounting_snapshot=snapshot)),
        configuration=ForecastRunConfiguration(
            as_of=scenario.as_of,
            horizon_days=scenario.horizon_days,
        ),
        rule_provider=lambda: scenario.fiscal_rules,
    )

    view = build_forecast_view_model(facade.run())

    assert any(
        "НДС по обратному начислению" in gap.impact
        for gap in view.data_gaps
    )
    assert view.fiscal_calculations[0].resolved is False
