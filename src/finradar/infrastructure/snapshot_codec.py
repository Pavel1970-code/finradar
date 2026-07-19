import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any

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
    IntegrationReference,
    SourceDataIssue,
    SourceIssueSeverity,
)


SCHEMA_VERSION = 3
SUPPORTED_SCHEMA_VERSIONS = {1, 2, 3}


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
            )
            for item in payload["events"]
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
    }


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
