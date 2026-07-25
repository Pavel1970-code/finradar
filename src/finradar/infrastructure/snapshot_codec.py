import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from finradar.domain.financial_snapshot import (
    AccountBalance,
    AccountingMetric,
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
from finradar.domain.payroll import (
    PayrollRecord,
    PayrollRecordStatus,
    PayrollPaymentForm,
    PayrollTaxTreatment,
    PensionParticipationStatus,
)


SCHEMA_VERSION = 5
SUPPORTED_SCHEMA_VERSIONS = {1, 2, 3, 4, 5}


def encode_snapshot(snapshot: FinancialSnapshot) -> str:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "source_system": snapshot.source_system,
        "captured_at": snapshot.captured_at.isoformat(),
        "available_datasets": sorted(item.value for item in snapshot.available_datasets),
        "company": _company_to_dict(snapshot.company),
        "balances": [_balance_to_dict(item) for item in snapshot.balances],
        "metrics": [_metric_to_dict(item) for item in snapshot.metrics],
        "events": [_event_to_dict(item) for item in snapshot.events],
        "payroll_records": [
            _payroll_record_to_dict(item) for item in snapshot.payroll_records
        ],
        "source_issues": [_source_issue_to_dict(item) for item in snapshot.source_issues],
        "source_cursor": snapshot.source_cursor,
        "integration_references": [
            _integration_reference_to_dict(item)
            for item in snapshot.integration_references
        ],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def decode_snapshot(content_json: str) -> FinancialSnapshot:
    payload: dict[str, Any] = json.loads(content_json)
    schema_version = payload.get("schema_version")
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise ValueError("Unsupported financial snapshot schema version.")

    company_payload = payload["company"]
    company = (
        CompanyProfile(
            external_id=company_payload["external_id"],
            name=company_payload["name"],
            base_currency=company_payload["base_currency"],
            jurisdiction=company_payload["jurisdiction"],
            tax_regime=company_payload["tax_regime"],
        )
        if company_payload is not None
        else None
    )
    return FinancialSnapshot(
        source_system=payload["source_system"],
        captured_at=datetime.fromisoformat(payload["captured_at"]),
        available_datasets=frozenset(
            DatasetKind(item) for item in payload["available_datasets"]
        ),
        company=company,
        balances=tuple(
            AccountBalance(
                external_id=item["external_id"],
                name=item["name"],
                currency=item["currency"],
                amount=Decimal(item["amount"]),
                balance_date=date.fromisoformat(item["balance_date"]),
            )
            for item in payload["balances"]
        ),
        metrics=tuple(
            AccountingMetric(
                code=item["code"],
                amount=Decimal(item["amount"]),
                currency=item["currency"],
                period_start=date.fromisoformat(item["period_start"]),
                period_end=date.fromisoformat(item["period_end"]),
                source_reference=item["source_reference"],
            )
            for item in payload.get("metrics", [])
        ),
        events=tuple(
            FinancialEvent(
                external_id=item["external_id"],
                title=item["title"],
                amount=Decimal(item["amount"]),
                currency=item["currency"],
                due_date=date.fromisoformat(item["due_date"]),
                direction=FinancialDirection(item["direction"]),
                kind=FinancialEventKind(item["kind"]),
                status=FinancialEventStatus(
                    item.get("status", FinancialEventStatus.PLANNED.value)
                ),
                settled_amount=Decimal(item.get("settled_amount", "0.00")),
                obligation_key=item.get("obligation_key"),
                related_obligation_key=item.get("related_obligation_key"),
                fiscal_consequence_type=item.get("fiscal_consequence_type"),
                category=item["category"],
                account_external_id=item["account_external_id"],
                source_reference=item.get("source_reference", ""),
                bank_transaction_id=item.get("bank_transaction_id"),
                counterparty=_counterparty_from_dict(item.get("counterparty")),
                payment_purpose=item.get("payment_purpose", ""),
                payment_basis=_payment_basis_from_dict(item.get("payment_basis")),
                period_start=(
                    date.fromisoformat(item["period_start"])
                    if item.get("period_start") is not None
                    else None
                ),
                period_end=(
                    date.fromisoformat(item["period_end"])
                    if item.get("period_end") is not None
                    else None
                ),
            )
            for item in payload["events"]
        ),
        payroll_records=tuple(
            PayrollRecord(
                external_id=item["external_id"],
                payroll_run_id=item["payroll_run_id"],
                employee_local_id=item["employee_local_id"],
                period_start=date.fromisoformat(item["period_start"]),
                period_end=date.fromisoformat(item["period_end"]),
                payment_date=date.fromisoformat(item["payment_date"]),
                currency=item["currency"],
                status=PayrollRecordStatus(item["status"]),
                payment_form=PayrollPaymentForm(item["payment_form"]),
                gross_cash_compensation=Decimal(item["gross_cash_compensation"]),
                taxable_non_cash_benefit=Decimal(item["taxable_non_cash_benefit"]),
                income_tax_base=Decimal(item["income_tax_base"]),
                income_tax_withheld=Decimal(item["income_tax_withheld"]),
                pension_contribution_base=Decimal(
                    item["pension_contribution_base"]
                ),
                employee_pension_contribution=Decimal(
                    item["employee_pension_contribution"]
                ),
                employer_pension_contribution=Decimal(
                    item["employer_pension_contribution"]
                ),
                other_employee_withholdings=Decimal(
                    item["other_employee_withholdings"]
                ),
                net_salary_payable=Decimal(item["net_salary_payable"]),
                employer_other_costs=Decimal(item["employer_other_costs"]),
                pension_participation=PensionParticipationStatus(
                    item["pension_participation"]
                ),
                tax_treatment=PayrollTaxTreatment(item["tax_treatment"]),
                income_tax_remittance_due_date=date.fromisoformat(
                    item["income_tax_remittance_due_date"]
                ),
                payroll_declaration_due_date=date.fromisoformat(
                    item["payroll_declaration_due_date"]
                ),
                pension_contribution_due_date=date.fromisoformat(
                    item["pension_contribution_due_date"]
                ),
                state_pension_cofinancing=(
                    Decimal(item["state_pension_cofinancing"])
                    if item.get("state_pension_cofinancing") is not None
                    else None
                ),
                annual_pension_base_before=(
                    Decimal(item["annual_pension_base_before"])
                    if item.get("annual_pension_base_before") is not None
                    else None
                ),
                tax_treatment_reference=item.get("tax_treatment_reference", ""),
                source_reference=item.get("source_reference", ""),
            )
            for item in payload.get("payroll_records", [])
        ),
        source_issues=tuple(
            SourceDataIssue(
                code=item["code"],
                severity=SourceIssueSeverity(item["severity"]),
                dataset=DatasetKind(item["dataset"]),
                message=item["message"],
                impact=item["impact"],
                source_reference=item.get("source_reference", ""),
            )
            for item in payload.get("source_issues", [])
        ),
        source_cursor=payload.get("source_cursor"),
        integration_references=tuple(
            IntegrationReference(
                connector_kind=item["connector_kind"],
                source_system=item["source_system"],
                synchronization_run_id=item["synchronization_run_id"],
                cursor=item.get("cursor"),
            )
            for item in payload.get("integration_references", [])
        ),
    )


def _company_to_dict(company: CompanyProfile | None) -> dict[str, str | None] | None:
    if company is None:
        return None
    return {
        "external_id": company.external_id,
        "name": company.name,
        "base_currency": company.base_currency,
        "jurisdiction": company.jurisdiction,
        "tax_regime": company.tax_regime,
    }


def _balance_to_dict(balance: AccountBalance) -> dict[str, str]:
    return {
        "external_id": balance.external_id,
        "name": balance.name,
        "currency": balance.currency,
        "amount": str(balance.amount),
        "balance_date": balance.balance_date.isoformat(),
    }


def _metric_to_dict(metric: AccountingMetric) -> dict[str, str]:
    return {
        "code": metric.code,
        "amount": str(metric.amount),
        "currency": metric.currency,
        "period_start": metric.period_start.isoformat(),
        "period_end": metric.period_end.isoformat(),
        "source_reference": metric.source_reference,
    }


def _event_to_dict(event: FinancialEvent) -> dict[str, str | None]:
    return {
        "external_id": event.external_id,
        "title": event.title,
        "amount": str(event.amount),
        "currency": event.currency,
        "due_date": event.due_date.isoformat(),
        "direction": event.direction.value,
        "kind": event.kind.value,
        "status": event.status.value,
        "settled_amount": str(event.settled_amount),
        "obligation_key": event.obligation_key,
        "related_obligation_key": event.related_obligation_key,
        "fiscal_consequence_type": event.fiscal_consequence_type,
        "category": event.category,
        "account_external_id": event.account_external_id,
        "source_reference": event.source_reference,
        "bank_transaction_id": event.bank_transaction_id,
        "counterparty": _counterparty_to_dict(event.counterparty),
        "payment_purpose": event.payment_purpose,
        "payment_basis": _payment_basis_to_dict(event.payment_basis),
        "period_start": (
            event.period_start.isoformat() if event.period_start is not None else None
        ),
        "period_end": (
            event.period_end.isoformat() if event.period_end is not None else None
        ),
    }


def _payroll_record_to_dict(
    record: PayrollRecord,
) -> dict[str, str | None]:
    return {
        "external_id": record.external_id,
        "payroll_run_id": record.payroll_run_id,
        "employee_local_id": record.employee_local_id,
        "period_start": record.period_start.isoformat(),
        "period_end": record.period_end.isoformat(),
        "payment_date": record.payment_date.isoformat(),
        "currency": record.currency,
        "status": record.status.value,
        "payment_form": record.payment_form.value,
        "gross_cash_compensation": str(record.gross_cash_compensation),
        "taxable_non_cash_benefit": str(record.taxable_non_cash_benefit),
        "income_tax_base": str(record.income_tax_base),
        "income_tax_withheld": str(record.income_tax_withheld),
        "pension_contribution_base": str(record.pension_contribution_base),
        "employee_pension_contribution": str(
            record.employee_pension_contribution
        ),
        "employer_pension_contribution": str(
            record.employer_pension_contribution
        ),
        "other_employee_withholdings": str(record.other_employee_withholdings),
        "net_salary_payable": str(record.net_salary_payable),
        "employer_other_costs": str(record.employer_other_costs),
        "pension_participation": record.pension_participation.value,
        "tax_treatment": record.tax_treatment.value,
        "income_tax_remittance_due_date": (
            record.income_tax_remittance_due_date.isoformat()
        ),
        "payroll_declaration_due_date": (
            record.payroll_declaration_due_date.isoformat()
        ),
        "pension_contribution_due_date": (
            record.pension_contribution_due_date.isoformat()
        ),
        "state_pension_cofinancing": (
            str(record.state_pension_cofinancing)
            if record.state_pension_cofinancing is not None
            else None
        ),
        "annual_pension_base_before": (
            str(record.annual_pension_base_before)
            if record.annual_pension_base_before is not None
            else None
        ),
        "tax_treatment_reference": record.tax_treatment_reference,
        "source_reference": record.source_reference,
    }


def _counterparty_to_dict(
    counterparty: CounterpartyReference | None,
) -> dict[str, str] | None:
    if counterparty is None:
        return None
    return {
        "external_id": counterparty.external_id,
        "name": counterparty.name,
        "kind": counterparty.kind.value,
    }


def _counterparty_from_dict(value: object) -> CounterpartyReference | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("Financial event counterparty must be an object.")
    return CounterpartyReference(
        external_id=value["external_id"],
        name=value["name"],
        kind=CounterpartyKind(value["kind"]),
    )


def _payment_basis_to_dict(basis: PaymentBasis | None) -> dict[str, str] | None:
    if basis is None:
        return None
    return {
        "document_type": basis.document_type,
        "document_number": basis.document_number,
        "document_date": basis.document_date.isoformat(),
        "description": basis.description,
    }


def _payment_basis_from_dict(value: object) -> PaymentBasis | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("Financial event payment basis must be an object.")
    return PaymentBasis(
        document_type=value["document_type"],
        document_number=value["document_number"],
        document_date=date.fromisoformat(value["document_date"]),
        description=value.get("description", ""),
    )


def _source_issue_to_dict(issue: SourceDataIssue) -> dict[str, str]:
    return {
        "code": issue.code,
        "severity": issue.severity.value,
        "dataset": issue.dataset.value,
        "message": issue.message,
        "impact": issue.impact,
        "source_reference": issue.source_reference,
    }


def _integration_reference_to_dict(
    reference: IntegrationReference,
) -> dict[str, str | None]:
    return {
        "connector_kind": reference.connector_kind,
        "source_system": reference.source_system,
        "synchronization_run_id": reference.synchronization_run_id,
        "cursor": reference.cursor,
    }
