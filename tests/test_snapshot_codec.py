import json

from finradar.domain.financial_snapshot import FinancialEventStatus
from finradar.infrastructure.snapshot_codec import decode_snapshot


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
