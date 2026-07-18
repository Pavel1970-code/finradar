from datetime import date
from decimal import Decimal

from finradar.application.synchronization_service import synchronize_and_forecast
from finradar.domain.data_readiness import ReadinessStatus
from finradar.domain.financial_snapshot import DatasetKind
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

