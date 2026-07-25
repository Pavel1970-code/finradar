import json
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from finradar.demo.scenario import DemoScenarioRepository
from finradar.domain.data_readiness import ReadinessStatus, assess_forecast_readiness
from finradar.domain.georgia_payroll import (
    CURRENT_GEORGIA_PAYROLL_RULES,
    calculate_state_cofinancing,
    validate_georgian_payroll_record,
)
from finradar.domain.payroll import (
    PayrollRecord,
    PayrollRecordStatus,
    PayrollPaymentForm,
    PayrollTaxTreatment,
    PensionParticipationStatus,
)
from finradar.infrastructure.georgia_payroll_rule_repository import (
    GeorgiaPayrollRuleError,
    GeorgiaPayrollRuleRepository,
)


RULE_PATH = (
    Path(__file__).parents[1]
    / "src"
    / "finradar"
    / "regulatory"
    / "rules"
    / "georgia_payroll_rules_v1.json"
)


def valid_record() -> PayrollRecord:
    return PayrollRecord(
        external_id="row-1",
        payroll_run_id="run-2026-07",
        employee_local_id="employee-local-1",
        period_start=date(2026, 7, 1),
        period_end=date(2026, 7, 31),
        payment_date=date(2026, 7, 31),
        currency="GEL",
        status=PayrollRecordStatus.APPROVED,
        payment_form=PayrollPaymentForm.CASH,
        gross_cash_compensation=Decimal("2500.00"),
        taxable_non_cash_benefit=Decimal("0.00"),
        income_tax_base=Decimal("2500.00"),
        income_tax_withheld=Decimal("500.00"),
        pension_contribution_base=Decimal("2500.00"),
        employee_pension_contribution=Decimal("50.00"),
        employer_pension_contribution=Decimal("50.00"),
        other_employee_withholdings=Decimal("0.00"),
        net_salary_payable=Decimal("1950.00"),
        employer_other_costs=Decimal("0.00"),
        pension_participation=PensionParticipationStatus.PARTICIPANT,
        tax_treatment=PayrollTaxTreatment.STANDARD,
        income_tax_remittance_due_date=date(2026, 7, 31),
        payroll_declaration_due_date=date(2026, 8, 17),
        pension_contribution_due_date=date(2026, 8, 17),
        state_pension_cofinancing=Decimal("50.00"),
        annual_pension_base_before=Decimal("12500.00"),
        source_reference="fixture:payroll:1",
    )


def test_bundled_rules_match_verified_current_domain_rules() -> None:
    bundled = GeorgiaPayrollRuleRepository().load()

    assert (
        bundled.standard_income_tax_rate
        == CURRENT_GEORGIA_PAYROLL_RULES.standard_income_tax_rate
    )
    assert (
        bundled.state_cofinancing_tiers
        == CURRENT_GEORGIA_PAYROLL_RULES.state_cofinancing_tiers
    )
    assert bundled.standard_income_tax_rate == Decimal("0.20")
    assert bundled.employee_pension_rate == Decimal("0.02")
    assert bundled.employer_pension_rate == Decimal("0.02")
    assert bundled.payroll_declaration_day == 15
    assert any(
        source.source_id == "ge-funded-pension-law-12"
        and "/4280127/12/" in source.url
        for source in bundled.sources
    )


def test_valid_payroll_row_has_no_legal_or_arithmetic_findings() -> None:
    record = valid_record()

    assert validate_georgian_payroll_record(
        record,
        CURRENT_GEORGIA_PAYROLL_RULES,
    ) == ()
    assert record.employee_deductions == Decimal("550.00")
    assert record.pension_remittance_payable == Decimal("100.00")
    assert record.employer_total_cost == Decimal("2550.00")
    assert record.company_cash_outflow == Decimal("2550.00")


def test_state_cofinancing_is_split_across_annual_thresholds() -> None:
    result = calculate_state_cofinancing(
        Decimal("4000.00"),
        annual_base_before=Decimal("23000.00"),
        tiers=CURRENT_GEORGIA_PAYROLL_RULES.state_cofinancing_tiers,
    )

    assert result == Decimal("50.00")


def test_mismatched_net_tax_and_pension_are_visible() -> None:
    broken = replace(
        valid_record(),
        income_tax_withheld=Decimal("450.00"),
        employee_pension_contribution=Decimal("40.00"),
        net_salary_payable=Decimal("1900.00"),
    )

    codes = {
        item.code
        for item in validate_georgian_payroll_record(
            broken,
            CURRENT_GEORGIA_PAYROLL_RULES,
        )
    }

    assert codes >= {
        "payroll_net_arithmetic_mismatch",
        "payroll_income_tax_mismatch",
        "payroll_employee_pension_mismatch",
    }


def test_nonparticipant_cannot_carry_pension_amounts() -> None:
    broken = replace(
        valid_record(),
        pension_participation=PensionParticipationStatus.NOT_PARTICIPANT,
    )

    codes = {
        item.code
        for item in validate_georgian_payroll_record(
            broken,
            CURRENT_GEORGIA_PAYROLL_RULES,
        )
    }

    assert "payroll_pension_for_non_participant" in codes


def test_non_cash_tax_uses_month_end_and_mixed_row_must_be_split() -> None:
    non_cash = replace(
        valid_record(),
        payment_form=PayrollPaymentForm.NON_CASH,
        payment_date=date(2026, 7, 10),
        income_tax_remittance_due_date=date(2026, 7, 31),
        payroll_declaration_due_date=date(2026, 8, 17),
        pension_contribution_due_date=date(2026, 8, 17),
    )
    assert all(
        item.code != "payroll_income_tax_due_date_mismatch"
        for item in validate_georgian_payroll_record(
            non_cash,
            CURRENT_GEORGIA_PAYROLL_RULES,
        )
    )

    mixed = replace(non_cash, payment_form=PayrollPaymentForm.MIXED)
    codes = {
        item.code
        for item in validate_georgian_payroll_record(
            mixed,
            CURRENT_GEORGIA_PAYROLL_RULES,
        )
    }
    assert "payroll_mixed_payment_requires_split" in codes


def test_aggregate_calendar_row_cannot_coexist_with_payroll_breakdown() -> None:
    scenario = DemoScenarioRepository().load("georgia_vat_pilot")
    snapshot = scenario.accounting_snapshot
    net_event = next(
        item for item in snapshot.events if item.category == "payroll_net_salary"
    )
    aggregate = replace(
        net_event,
        external_id="duplicate-aggregate-payroll",
        category="payroll_aggregate",
    )
    snapshot = replace(snapshot, events=snapshot.events + (aggregate,))

    readiness = assess_forecast_readiness(snapshot, as_of=scenario.as_of)

    assert readiness.status is ReadinessStatus.BLOCKED
    assert "payroll_aggregate_conflicts_with_breakdown" in {
        item.code for item in readiness.issues
    }


def test_rule_checksum_rejects_modified_rate(tmp_path: Path) -> None:
    raw = json.loads(RULE_PATH.read_text(encoding="utf-8"))
    raw["payload"]["standard_income_tax_rate"] = "0.19"
    target = tmp_path / RULE_PATH.name
    target.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(GeorgiaPayrollRuleError, match="integrity"):
        GeorgiaPayrollRuleRepository(tmp_path).load()
