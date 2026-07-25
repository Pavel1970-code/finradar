from datetime import date, datetime, timezone
from decimal import Decimal

from finradar.application.accounting_connector import SynchronizationRequest
from finradar.application.integration_sdk import validate_accounting_snapshot
from finradar.domain.data_readiness import ReadinessStatus, assess_forecast_readiness
from finradar.domain.financial_snapshot import (
    DatasetKind,
    FinancialEventKind,
    SourceIssueSeverity,
)
from finradar.infrastructure.connectors.one_c import (
    FixtureOneCTransport,
    OneCAccountingConnector,
    OneCExtract,
    OneCMappingProfile,
)


AS_OF = date(2026, 7, 19)
CAPTURED_AT = datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc)


def complete_extract() -> OneCExtract:
    return OneCExtract(
        captured_at=CAPTURED_AT,
        company={
            "external_id": "company-1",
            "name": "Fictional 1C Company",
            "base_currency": "GEL",
            "jurisdiction": "GE",
            "tax_regime": "fictional-regime",
        },
        balances=(
            {
                "external_id": "account-1",
                "name": "Operating account",
                "currency": "GEL",
                "amount": "1100.00",
                "balance_date": AS_OF.isoformat(),
            },
        ),
        metrics=(
            {
                "code": "taxable_revenue",
                "amount": "5000.00",
                "currency": "GEL",
                "period_start": "2026-07-01",
                "period_end": "2026-07-18",
                "source_reference": "1c:ledger:1",
            },
        ),
        accounting_events=(
            {
                "external_id": "fact-1",
                "title": "Customer receipt",
                "amount": "100.00",
                "currency": "GEL",
                "due_date": AS_OF.isoformat(),
                "direction": "inflow",
                "status": "settled",
                "settled_amount": "100.00",
                "category": "customer_receipt",
                "account_external_id": "account-1",
                "source_reference": "1c:bank-document:1",
                "bank_transaction_id": "bank-1",
            },
        ),
        payment_events=(
            {
                "external_id": "planned-1",
                "title": "Supplier payment",
                "amount": "250.00",
                "currency": "GEL",
                "due_date": "2026-07-21",
                "direction": "outflow",
                "status": "confirmed",
                "settled_amount": "0",
                "category": "supplier",
                "account_external_id": "account-1",
                "source_reference": "1c:payment-calendar:1",
                "bank_transaction_id": "",
                "counterparty_external_id": "supplier-1",
                "counterparty_name": "Fictional supplier",
                "counterparty_kind": "supplier",
                "payment_purpose": "Payment for delivery",
                "document_type": "delivery_note",
                "document_number": "DELIVERY-1",
                "document_date": "2026-07-01",
                "period_start": "2026-07-01",
                "period_end": "2026-07-15",
            },
        ),
        payroll_records=(
            {
                "external_id": "payroll-row-1",
                "payroll_run_id": "PAY-2026-07",
                "employee_local_id": "employee-local-1",
                "period_start": "2026-07-01",
                "period_end": "2026-07-31",
                "payment_date": "2026-07-31",
                "currency": "GEL",
                "status": "approved",
                "payment_form": "cash",
                "gross_cash_compensation": "1000.00",
                "taxable_non_cash_benefit": "0.00",
                "income_tax_base": "1000.00",
                "income_tax_withheld": "200.00",
                "pension_contribution_base": "1000.00",
                "employee_pension_contribution": "20.00",
                "employer_pension_contribution": "20.00",
                "other_employee_withholdings": "0.00",
                "net_salary_payable": "780.00",
                "employer_other_costs": "0.00",
                "pension_participation": "participant",
                "tax_treatment": "standard",
                "income_tax_remittance_due_date": "2026-07-31",
                "payroll_declaration_due_date": "2026-08-17",
                "pension_contribution_due_date": "2026-08-17",
                "state_pension_cofinancing": "20.00",
                "annual_pension_base_before": "6000.00",
                "tax_treatment_reference": "Tax Code articles 81, 101 and 154",
                "source_reference": "1c:payroll:row-1",
            },
        ),
        next_cursor="1c-cursor-100",
    )


def connector_for(extract: OneCExtract) -> OneCAccountingConnector:
    return OneCAccountingConnector(
        source_system="one-c-fixture",
        transport=FixtureOneCTransport(extract),
        mapping=OneCMappingProfile(profile_id="canonical-fixture"),
    )


def test_one_c_fixture_maps_facts_calendar_and_incremental_cursor() -> None:
    connector = connector_for(complete_extract())

    snapshot = connector.synchronize(SynchronizationRequest(cursor="previous-cursor"))
    validate_accounting_snapshot(connector.capabilities(), snapshot)

    assert snapshot.company.name == "Fictional 1C Company"
    assert snapshot.balances[0].amount == Decimal("1100.00")
    assert snapshot.metrics[0].code == "taxable_revenue"
    assert snapshot.events[0].kind is FinancialEventKind.FACT
    assert snapshot.events[0].bank_transaction_id == "bank-1"
    assert snapshot.events[1].kind is FinancialEventKind.PLANNED
    assert snapshot.events[1].counterparty.name == "Fictional supplier"
    assert snapshot.events[1].payment_basis.document_number == "DELIVERY-1"
    assert snapshot.events[1].period_end == date(2026, 7, 15)
    assert snapshot.payroll_records[0].net_salary_payable == Decimal("780.00")
    assert snapshot.payroll_records[0].employer_total_cost == Decimal("1020.00")
    assert DatasetKind.PAYROLL in snapshot.available_datasets
    assert snapshot.source_cursor == "1c-cursor-100"
    assert snapshot.source_issues == ()


def test_one_c_invalid_record_becomes_visible_data_gap() -> None:
    source = complete_extract()
    extract = OneCExtract(
        captured_at=source.captured_at,
        company=source.company,
        balances=source.balances
        + (
            {
                "external_id": "broken-account",
                "name": "Broken",
                "currency": "GEL",
                "amount": "not-a-number",
                "balance_date": AS_OF.isoformat(),
            },
        ),
        metrics=source.metrics,
        accounting_events=source.accounting_events,
        payment_events=source.payment_events,
        payroll_records=source.payroll_records,
    )

    snapshot = connector_for(extract).synchronize(SynchronizationRequest())
    readiness = assess_forecast_readiness(snapshot, as_of=AS_OF)

    assert len(snapshot.balances) == 1
    assert readiness.status is ReadinessStatus.LIMITED
    issue = next(item for item in snapshot.source_issues if "balance" in item.code)
    assert issue.severity is SourceIssueSeverity.WARNING
    assert issue.source_reference == "balance:2"


def test_one_c_custom_field_profile_isolated_from_core_model() -> None:
    profile = OneCMappingProfile(
        profile_id="custom-company-profile",
        company_fields={
            "external_id": "Ref_Key",
            "name": "Description",
            "base_currency": "CurrencyCode",
            "jurisdiction": "CountryCode",
            "tax_regime": "TaxMode",
        },
    )
    transport = FixtureOneCTransport(
        OneCExtract(
            captured_at=CAPTURED_AT,
            company={
                "Ref_Key": "custom-company",
                "Description": "Custom 1C Company",
                "CurrencyCode": "gel",
                "CountryCode": "GE",
                "TaxMode": "small-business",
            },
            balances=(),
            metrics=(),
            accounting_events=(),
            payment_events=(),
        )
    )
    connector = OneCAccountingConnector(
        source_system="one-c-custom",
        transport=transport,
        mapping=profile,
    )

    snapshot = connector.synchronize(SynchronizationRequest())

    assert snapshot.company.external_id == "custom-company"
    assert snapshot.company.base_currency == "GEL"
    assert DatasetKind.COMPANY_PROFILE in snapshot.available_datasets
