import json
from dataclasses import replace
from pathlib import Path

import pytest

from finradar.demo.scenario import DemoScenarioRepository
from finradar.domain.data_readiness import assess_forecast_readiness
from finradar.domain.financial_snapshot import DatasetKind
from finradar.domain.obligation_catalog import (
    CashFlowTreatment,
    FormulaStatus,
    ObligationKind,
)
from finradar.infrastructure.obligation_catalog_repository import (
    ObligationCatalogError,
    ObligationCatalogRepository,
)


CATALOG_PATH = (
    Path(__file__).parents[1]
    / "src"
    / "finradar"
    / "regulatory"
    / "catalogs"
    / "georgia_mandatory_obligations_v1.json"
)


def test_georgian_catalog_is_versioned_complete_and_has_no_rates() -> None:
    catalog = ObligationCatalogRepository().load_georgia()

    assert catalog.version == 1
    assert catalog.jurisdiction == "GE"
    assert catalog.rates_included is False
    assert len(catalog.entries) == 42
    assert {
        item.instrument_id
        for item in catalog.entries
        if item.kind is ObligationKind.TAX
    } == {
        "ge-tax-income",
        "ge-tax-profit",
        "ge-tax-vat",
        "ge-tax-excise",
        "ge-tax-import",
        "ge-tax-property",
    }
    raw = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    assert not _contains_rate_key(raw["payload"]["entries"])


def test_payroll_catalog_separates_cash_without_double_counting_gross_salary() -> None:
    catalog = ObligationCatalogRepository().load_georgia()
    payroll = {item.instrument_id: item for item in catalog.group("ge-payroll")}

    assert (
        payroll["ge-payroll-gross-salary"].cash_flow_treatment
        is CashFlowTreatment.CALCULATION_BASE
    )
    assert (
        payroll["ge-payroll-net-salary"].cash_flow_treatment
        is CashFlowTreatment.DIRECT_OUTFLOW
    )
    assert (
        payroll["ge-withholding-employment-income-tax"].cash_flow_treatment
        is CashFlowTreatment.WITHHELD_REMITTANCE
    )
    assert (
        payroll["ge-pension-employee-contribution"].cash_flow_treatment
        is CashFlowTreatment.WITHHELD_REMITTANCE
    )
    assert (
        payroll["ge-pension-employer-contribution"].cash_flow_treatment
        is CashFlowTreatment.EMPLOYER_ADDITIONAL_OUTFLOW
    )
    assert (
        payroll["ge-pension-state-cofinancing"].cash_flow_treatment
        is CashFlowTreatment.NO_COMPANY_CASH_FLOW
    )
    assert all(
        item.formula_status is FormulaStatus.PARTIALLY_IMPLEMENTED
        and item.calculation_rule_ids == ("ge-payroll-standard",)
        for instrument_id, item in payroll.items()
        if instrument_id != "ge-payroll-reporting"
    )


def test_catalog_records_repealed_social_insurance_and_no_separate_payroll_tax() -> None:
    catalog = ObligationCatalogRepository().load_georgia()
    findings = {item.finding_id: item for item in catalog.findings}

    assert "ge-no-current-general-social-insurance-contribution" in findings
    assert "1 января 2006" in findings[
        "ge-no-current-general-social-insurance-contribution"
    ].statement
    assert "ge-no-separate-payroll-tax" in findings


def test_vat_catalog_entry_links_to_existing_deterministic_rule() -> None:
    catalog = ObligationCatalogRepository().load_georgia()
    vat = catalog.entry("ge-tax-vat")
    credit = catalog.entry("ge-vat-credit-or-refund")

    assert vat.formula_status is FormulaStatus.PARTIALLY_IMPLEMENTED
    assert vat.calculation_rule_ids == ("ge-vat-standard",)
    assert credit.calculation_rule_ids == ("ge-vat-standard",)


def test_catalog_checksum_rejects_modified_content(tmp_path: Path) -> None:
    raw = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    raw["payload"]["entries"][0]["name_ru"] = "Изменённое название"
    target = tmp_path / CATALOG_PATH.name
    target.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ObligationCatalogError, match="integrity"):
        ObligationCatalogRepository(tmp_path).load_georgia()


def test_georgian_aggregate_payroll_is_reported_as_incomplete() -> None:
    scenario = DemoScenarioRepository().load("georgia_vat_pilot")
    snapshot = scenario.accounting_snapshot
    net_event = next(
        item for item in snapshot.events if item.category == "payroll_net_salary"
    )
    aggregate_event = replace(
        net_event,
        external_id="aggregate-payroll",
        title="Агрегированная зарплата",
        amount=net_event.amount,
        category="payroll_aggregate",
    )
    snapshot = replace(
        snapshot,
        available_datasets=snapshot.available_datasets - {DatasetKind.PAYROLL},
        payroll_records=(),
        events=tuple(
            item
            for item in snapshot.events
            if item.category
            not in {"payroll_net_salary", "payroll_income_tax", "payroll_pension"}
        )
        + (aggregate_event,),
    )

    report = assess_forecast_readiness(
        snapshot,
        as_of=scenario.as_of,
    )

    issue = next(
        item
        for item in report.issues
        if item.code == "payroll_breakdown_unavailable"
    )
    assert "чистую выплату, налог и пенсионные взносы" in issue.message
    assert "дополнительный пенсионный расход работодателя" in issue.impact


def test_non_georgian_payroll_does_not_claim_georgian_components() -> None:
    scenario = DemoScenarioRepository().load("georgia_vat_pilot")
    assert scenario.accounting_snapshot.company is not None
    snapshot = replace(
        scenario.accounting_snapshot,
        company=replace(scenario.accounting_snapshot.company, jurisdiction="XX"),
    )

    report = assess_forecast_readiness(snapshot, as_of=scenario.as_of)

    assert all(item.code != "payroll_breakdown_unavailable" for item in report.issues)


def _contains_rate_key(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            (
                "rate" in str(key).lower()
                and str(key) != "rate_rule_ids"
            )
            or _contains_rate_key(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_rate_key(item) for item in value)
    return False
