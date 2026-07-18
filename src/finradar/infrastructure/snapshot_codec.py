import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from finradar.domain.financial_snapshot import (
    AccountBalance,
    CompanyProfile,
    DatasetKind,
    FinancialDirection,
    FinancialEvent,
    FinancialEventKind,
    FinancialSnapshot,
)


SCHEMA_VERSION = 1


def encode_snapshot(snapshot: FinancialSnapshot) -> str:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "source_system": snapshot.source_system,
        "captured_at": snapshot.captured_at.isoformat(),
        "available_datasets": sorted(item.value for item in snapshot.available_datasets),
        "company": _company_to_dict(snapshot.company),
        "balances": [_balance_to_dict(item) for item in snapshot.balances],
        "events": [_event_to_dict(item) for item in snapshot.events],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def decode_snapshot(content_json: str) -> FinancialSnapshot:
    payload: dict[str, Any] = json.loads(content_json)
    if payload.get("schema_version") != SCHEMA_VERSION:
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
        events=tuple(
            FinancialEvent(
                external_id=item["external_id"],
                title=item["title"],
                amount=Decimal(item["amount"]),
                currency=item["currency"],
                due_date=date.fromisoformat(item["due_date"]),
                direction=FinancialDirection(item["direction"]),
                kind=FinancialEventKind(item["kind"]),
                category=item["category"],
                account_external_id=item["account_external_id"],
            )
            for item in payload["events"]
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


def _event_to_dict(event: FinancialEvent) -> dict[str, str | None]:
    return {
        "external_id": event.external_id,
        "title": event.title,
        "amount": str(event.amount),
        "currency": event.currency,
        "due_date": event.due_date.isoformat(),
        "direction": event.direction.value,
        "kind": event.kind.value,
        "category": event.category,
        "account_external_id": event.account_external_id,
    }

