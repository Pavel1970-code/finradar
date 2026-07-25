import json
from datetime import date, datetime, timezone
from decimal import Decimal

from finradar.domain.financial_snapshot import (
    AccountBalance,
    CompanyProfile,
    CounterpartyKind,
    CounterpartyReference,
    DatasetKind,
    FinancialDirection,
    FinancialEvent,
    FinancialEventKind,
    FinancialEventStatus,
    FinancialSnapshot,
    IntegrationReference,
    PaymentBasis,
    SourceDataIssue,
    SourceIssueSeverity,
)
from finradar.infrastructure.snapshot_codec import decode_snapshot, encode_snapshot
from finradar.domain.payroll import (
    PayrollRecord,
    PayrollRecordStatus,
    PayrollPaymentForm,
    PayrollTaxTreatment,
    PensionParticipationStatus,
)


def test_version_one_snapshot_remains_readable() -> None:
    content = json.dumps(
        {
            "schema_version": 1,
            "source_system": "legacy-demo",
            "captured_at": "2026-07-18T00:00:00+00:00",
            "available_datasets": ["company_profile", "payment_calendar"],
            "company": {
                "external_id": "company-1",
                "name": "Fictional Company",
                "base_currency": "GEL",
                "jurisdiction": None,
                "tax_regime": None,
            },
            "balances": [],
            "events": [
                {
                    "external_id": "event-1",
                    "title": "Legacy event",
                    "amount": "10.00",
                    "currency": "GEL",
                    "due_date": "2026-07-20",
                    "direction": "outflow",
                    "kind": "planned",
                    "category": None,
                    "account_external_id": None,
                }
            ],
        }
    )

    snapshot = decode_snapshot(content)

    assert snapshot.metrics == ()
    assert snapshot.events[0].status is FinancialEventStatus.PLANNED


def test_version_five_snapshot_preserves_payment_payroll_and_provenance() -> None:
    snapshot = FinancialSnapshot(
        source_system="one-c",
        captured_at=datetime(2026, 7, 19, tzinfo=timezone.utc),
        available_datasets=frozenset(
            {DatasetKind.COMPANY_PROFILE, DatasetKind.ACCOUNT_BALANCES}
        ),
        company=CompanyProfile(
            external_id="company-1",
            name="Fictional Company",
            base_currency="GEL",
        ),
        balances=(
            AccountBalance(
                external_id="account-1",
                name="Operating account",
                currency="GEL",
                amount=Decimal("100.00"),
                balance_date=date(2026, 7, 19),
            ),
        ),
        events=(
            FinancialEvent(
                external_id="payment-1",
                title="Supplier payment",
                amount=Decimal("75.00"),
                currency="GEL",
                due_date=date(2026, 7, 21),
                direction=FinancialDirection.OUTFLOW,
                kind=FinancialEventKind.PLANNED,
                counterparty=CounterpartyReference(
                    external_id="supplier-1",
                    name="Fictional supplier",
                    kind=CounterpartyKind.SUPPLIER,
                ),
                payment_purpose="Fictional delivery",
                payment_basis=PaymentBasis(
                    document_type="delivery_note",
                    document_number="DEMO-1",
                    document_date=date(2026, 7, 1),
                ),
                period_start=date(2026, 7, 1),
                period_end=date(2026, 7, 15),
            ),
        ),
        payroll_records=(
            PayrollRecord(
                external_id="payroll-row-1",
                payroll_run_id="run-1",
                employee_local_id="employee-local-1",
                period_start=date(2026, 7, 1),
                period_end=date(2026, 7, 31),
                payment_date=date(2026, 7, 31),
                currency="GEL",
                status=PayrollRecordStatus.APPROVED,
                payment_form=PayrollPaymentForm.CASH,
                gross_cash_compensation=Decimal("1000.00"),
                taxable_non_cash_benefit=Decimal("0.00"),
                income_tax_base=Decimal("1000.00"),
                income_tax_withheld=Decimal("200.00"),
                pension_contribution_base=Decimal("1000.00"),
                employee_pension_contribution=Decimal("20.00"),
                employer_pension_contribution=Decimal("20.00"),
                other_employee_withholdings=Decimal("0.00"),
                net_salary_payable=Decimal("780.00"),
                employer_other_costs=Decimal("0.00"),
                pension_participation=PensionParticipationStatus.PARTICIPANT,
                tax_treatment=PayrollTaxTreatment.STANDARD,
                income_tax_remittance_due_date=date(2026, 7, 31),
                payroll_declaration_due_date=date(2026, 8, 17),
                pension_contribution_due_date=date(2026, 8, 17),
                state_pension_cofinancing=Decimal("20.00"),
                annual_pension_base_before=Decimal("0.00"),
                tax_treatment_reference="Tax Code articles 81, 101 and 154",
                source_reference="fixture:payroll:1",
            ),
        ),
        source_issues=(
            SourceDataIssue(
                code="fixture_gap",
                severity=SourceIssueSeverity.WARNING,
                dataset=DatasetKind.BANK_TRANSACTIONS,
                message="Fixture gap",
                impact="Fixture impact",
                source_reference="fixture:1",
            ),
        ),
        source_cursor="one-c-cursor",
        integration_references=(
            IntegrationReference(
                connector_kind="bank",
                source_system="fictional-bank",
                synchronization_run_id="run-1",
                cursor="bank-cursor",
            ),
        ),
    )

    restored = decode_snapshot(encode_snapshot(snapshot))

    assert restored == snapshot
