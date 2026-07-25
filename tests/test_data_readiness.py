from datetime import date, datetime, timezone
from decimal import Decimal

from finradar.domain.data_readiness import ReadinessStatus, assess_forecast_readiness
from finradar.domain.financial_snapshot import (
    AccountBalance,
    CompanyProfile,
    DatasetKind,
    FinancialDirection,
    FinancialEvent,
    FinancialEventKind,
    FinancialSnapshot,
)


AS_OF = date(2026, 7, 18)


def make_snapshot(*, available_datasets: frozenset[DatasetKind]) -> FinancialSnapshot:
    return FinancialSnapshot(
        source_system="demo",
        captured_at=datetime(2026, 7, 18, tzinfo=timezone.utc),
        available_datasets=available_datasets,
        company=CompanyProfile(
            external_id="company-1",
            name="Fictional Company",
            base_currency="GEL",
            jurisdiction="GE",
            tax_regime="fictional-regime",
        ),
        balances=(
            AccountBalance(
                external_id="account-1",
                name="Main account",
                currency="GEL",
                amount=Decimal("1000.00"),
                balance_date=AS_OF,
            ),
        ),
    )


def test_ready_when_required_datasets_are_present_even_if_calendar_is_empty() -> None:
    snapshot = make_snapshot(
        available_datasets=frozenset(
            {
                DatasetKind.COMPANY_PROFILE,
                DatasetKind.ACCOUNT_BALANCES,
                DatasetKind.ACCOUNTING_FACTS,
                DatasetKind.PAYMENT_CALENDAR,
            }
        )
    )

    report = assess_forecast_readiness(snapshot, as_of=AS_OF)

    assert report.status is ReadinessStatus.READY
    assert report.issues == ()


def test_missing_payment_calendar_limits_but_does_not_block_forecast() -> None:
    snapshot = make_snapshot(
        available_datasets=frozenset(
            {
                DatasetKind.COMPANY_PROFILE,
                DatasetKind.ACCOUNT_BALANCES,
                DatasetKind.ACCOUNTING_FACTS,
            }
        )
    )

    report = assess_forecast_readiness(snapshot, as_of=AS_OF)

    assert report.status is ReadinessStatus.LIMITED
    assert {issue.code for issue in report.issues} == {"payment_calendar_unavailable"}


def test_missing_balances_blocks_forecast() -> None:
    snapshot = FinancialSnapshot(
        source_system="demo",
        captured_at=datetime(2026, 7, 18, tzinfo=timezone.utc),
        available_datasets=frozenset(
            {DatasetKind.COMPANY_PROFILE, DatasetKind.PAYMENT_CALENDAR}
        ),
        company=CompanyProfile(
            external_id="company-1",
            name="Fictional Company",
            base_currency="GEL",
            jurisdiction="GE",
            tax_regime="fictional-regime",
        ),
    )

    report = assess_forecast_readiness(snapshot, as_of=AS_OF)

    assert report.status is ReadinessStatus.BLOCKED
    assert "account_balances_unavailable" in {issue.code for issue in report.issues}


def test_missing_counterparty_and_basis_limit_but_do_not_remove_payment() -> None:
    snapshot = make_snapshot(
        available_datasets=frozenset(
            {
                DatasetKind.COMPANY_PROFILE,
                DatasetKind.ACCOUNT_BALANCES,
                DatasetKind.ACCOUNTING_FACTS,
                DatasetKind.PAYMENT_CALENDAR,
            }
        )
    )
    snapshot = FinancialSnapshot(
        source_system=snapshot.source_system,
        captured_at=snapshot.captured_at,
        available_datasets=snapshot.available_datasets,
        company=snapshot.company,
        balances=snapshot.balances,
        events=(
            FinancialEvent(
                external_id="payment-1",
                title="Unidentified supplier payment",
                amount=Decimal("100.00"),
                currency="GEL",
                due_date=AS_OF,
                direction=FinancialDirection.OUTFLOW,
                kind=FinancialEventKind.PLANNED,
            ),
        ),
    )

    report = assess_forecast_readiness(snapshot, as_of=AS_OF)

    assert report.status is ReadinessStatus.LIMITED
    assert {issue.code for issue in report.issues} == {
        "payment_counterparty_missing",
        "payment_basis_missing",
    }


def test_settlement_above_obligation_blocks_forecast() -> None:
    snapshot = make_snapshot(
        available_datasets=frozenset(
            {
                DatasetKind.COMPANY_PROFILE,
                DatasetKind.ACCOUNT_BALANCES,
                DatasetKind.ACCOUNTING_FACTS,
                DatasetKind.PAYMENT_CALENDAR,
            }
        )
    )
    snapshot = FinancialSnapshot(
        source_system=snapshot.source_system,
        captured_at=snapshot.captured_at,
        available_datasets=snapshot.available_datasets,
        company=snapshot.company,
        balances=snapshot.balances,
        events=(
            FinancialEvent(
                external_id="payment-1",
                title="Invalid partial payment",
                amount=Decimal("100.00"),
                settled_amount=Decimal("120.00"),
                currency="GEL",
                due_date=AS_OF,
                direction=FinancialDirection.OUTFLOW,
                kind=FinancialEventKind.PLANNED,
            ),
        ),
    )

    report = assess_forecast_readiness(snapshot, as_of=AS_OF)

    assert report.status is ReadinessStatus.BLOCKED
    assert "payment_settlement_exceeds_amount" in {
        issue.code for issue in report.issues
    }
