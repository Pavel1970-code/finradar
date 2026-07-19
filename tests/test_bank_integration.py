from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import sessionmaker

from finradar.application.bank_connector import BankSynchronizationRequest
from finradar.application.accounting_connector import SynchronizationRequest
from finradar.application.bank_reconciliation import (
    BankMatchMethod,
    BankMatchStatus,
    reconcile_bank_batch,
)
from finradar.application.synchronization_service import synchronize_and_forecast
from finradar.domain.banking import (
    BankStatement,
    BankSynchronizationBatch,
    BankTransaction,
    BankTransactionDirection,
)
from finradar.domain.data_readiness import ReadinessStatus
from finradar.domain.financial_snapshot import DatasetKind
from finradar.infrastructure.bank_synchronization_history import (
    SqlAlchemyBankSynchronizationHistory,
)
from finradar.infrastructure.connectors.bank import (
    BankCsvMappingProfile,
    CsvBankStatementConnector,
    FixtureBankConnector,
)
from finradar.infrastructure.connectors.one_c import (
    FixtureOneCTransport,
    OneCAccountingConnector,
    OneCExtract,
    OneCMappingProfile,
)
from finradar.infrastructure.database import migrate_database


AS_OF = date(2026, 7, 19)
CAPTURED_AT = datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc)


def bank_batch(*, transaction_id: str = "bank-1") -> BankSynchronizationBatch:
    return BankSynchronizationBatch(
        source_system="fictional-bank",
        captured_at=CAPTURED_AT,
        available=True,
        statements=(
            BankStatement(
                statement_id="statement-1",
                account_external_id="account-1",
                period_start=AS_OF,
                period_end=AS_OF,
                opening_balance=Decimal("1000.00"),
                closing_balance=Decimal("1100.00"),
                transactions=(
                    BankTransaction(
                        external_id=transaction_id,
                        account_external_id="account-1",
                        booking_date=AS_OF,
                        value_date=AS_OF,
                        direction=BankTransactionDirection.CREDIT,
                        amount=Decimal("100.00"),
                        currency="GEL",
                        description="Fictional customer receipt",
                    ),
                ),
            ),
        ),
        next_cursor="bank-cursor-1",
    )


def accounting_connector() -> OneCAccountingConnector:
    extract = OneCExtract(
        captured_at=CAPTURED_AT,
        company={
            "external_id": "company-1",
            "name": "Fictional Company",
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
        metrics=(),
        accounting_events=(
            {
                "external_id": "accounting-fact-1",
                "title": "Customer receipt",
                "amount": "100.00",
                "currency": "GEL",
                "due_date": AS_OF.isoformat(),
                "direction": "inflow",
                "status": "settled",
                "settled_amount": "100.00",
                "category": "receipt",
                "account_external_id": "account-1",
                "source_reference": "1c:document:1",
                "bank_transaction_id": "bank-1",
            },
        ),
        payment_events=(),
    )
    return OneCAccountingConnector(
        source_system="one-c-fixture",
        transport=FixtureOneCTransport(extract),
        mapping=OneCMappingProfile(profile_id="fixture"),
    )


def test_bank_and_one_c_reconcile_inside_full_forecast_pipeline(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'integration.db'}")
    migrate_database(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    history = SqlAlchemyBankSynchronizationHistory(session_factory)

    outcome = synchronize_and_forecast(
        accounting_connector(),
        as_of=AS_OF,
        bank_connector=FixtureBankConnector(bank_batch()),
        bank_recorder=history,
    )

    assert outcome.readiness.status is ReadinessStatus.READY
    assert outcome.forecast is not None
    assert outcome.bank_reconciliation.matched_count == 1
    assert outcome.bank_reconciliation.items[0].method is BankMatchMethod.TRANSACTION_ID
    assert outcome.bank_synchronization_run_id is not None
    assert DatasetKind.BANK_TRANSACTIONS in outcome.snapshot.available_datasets
    assert outcome.snapshot.integration_references[0].synchronization_run_id == (
        outcome.bank_synchronization_run_id
    )
    assert history.load_batch(outcome.bank_synchronization_run_id) == bank_batch()


def test_missing_and_stale_bank_operations_are_reported_not_guessed() -> None:
    snapshot = accounting_connector().synchronize(SynchronizationRequest())
    stale = BankSynchronizationBatch(
        source_system="fictional-bank",
        captured_at=CAPTURED_AT,
        available=True,
        statements=(
            BankStatement(
                statement_id="old-statement",
                account_external_id="account-1",
                period_start=date(2026, 7, 10),
                period_end=date(2026, 7, 14),
                opening_balance=None,
                closing_balance=None,
                transactions=(
                    BankTransaction(
                        external_id="bank-missing-in-accounting",
                        account_external_id="account-1",
                        booking_date=date(2026, 7, 14),
                        value_date=date(2026, 7, 14),
                        direction=BankTransactionDirection.DEBIT,
                        amount=Decimal("35.00"),
                        currency="GEL",
                        description="Unrecorded bank fee",
                    ),
                ),
            ),
        ),
    )

    report = reconcile_bank_batch(snapshot, stale, as_of=AS_OF)

    assert report.items[0].status is BankMatchStatus.MISSING_IN_ACCOUNTING
    assert {issue.code for issue in report.source_issues} == {
        "bank_coverage_stale",
        "bank_transactions_missing_in_accounting",
    }


def test_csv_bank_adapter_deduplicates_and_reports_bad_rows(tmp_path: Path) -> None:
    statement_path = tmp_path / "statement.csv"
    statement_path.write_text(
        "transaction_id,booking_date,value_date,direction,amount,currency,description,"
        "reference,status,counterparty_name,counterparty_account\n"
        "tx-1,2026-07-19,2026-07-19,credit,100.00,GEL,Receipt,INV-1,booked,A,GE1\n"
        "tx-1,2026-07-19,2026-07-19,credit,100.00,GEL,Receipt,INV-1,booked,A,GE1\n"
        "tx-2,2026-07-19,2026-07-19,debit,broken,GEL,Expense,INV-2,booked,B,GE2\n",
        encoding="utf-8",
    )
    connector = CsvBankStatementConnector(
        source_system="csv-bank",
        statement_path=statement_path,
        account_external_id="account-1",
        statement_id="csv-statement-1",
        period_start=AS_OF,
        period_end=AS_OF,
        mapping=BankCsvMappingProfile(profile_id="canonical-csv"),
    )

    batch = connector.synchronize(BankSynchronizationRequest())

    assert len(batch.transactions) == 1
    assert {issue.code for issue in batch.source_issues} == {
        "bank_duplicate_transaction",
        "bank_row_mapping_failed",
    }
    assert len(batch.next_cursor) == 64


def test_bank_history_is_immutable(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'history.db'}")
    migrate_database(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    history = SqlAlchemyBankSynchronizationHistory(session_factory)
    run_id = history.record(bank_batch())

    with pytest.raises(DatabaseError, match="immutable"):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE bank_statement_snapshots SET content_json = '{}' "
                    "WHERE bank_synchronization_run_id = :run_id"
                ),
                {"run_id": run_id},
            )
