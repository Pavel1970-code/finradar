from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from finradar.application.accounting_connector import ConnectorCapabilities
from finradar.application.bank_connector import BankConnectorCapabilities
from finradar.application.integration_sdk import (
    ConnectorContractError,
    validate_accounting_snapshot,
    validate_bank_batch,
)
from finradar.domain.banking import (
    BankStatement,
    BankSynchronizationBatch,
    BankTransaction,
    BankTransactionDirection,
)
from finradar.domain.financial_snapshot import (
    AccountBalance,
    CompanyProfile,
    DatasetKind,
    FinancialSnapshot,
)


CAPTURED_AT = datetime(2026, 7, 19, tzinfo=timezone.utc)


def accounting_snapshot() -> FinancialSnapshot:
    return FinancialSnapshot(
        source_system="accounting-fixture",
        captured_at=CAPTURED_AT,
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
    )


def test_accounting_contract_rejects_writable_connector() -> None:
    capabilities = ConnectorCapabilities(
        source_system="accounting-fixture",
        datasets=frozenset(
            {DatasetKind.COMPANY_PROFILE, DatasetKind.ACCOUNT_BALANCES}
        ),
        supports_incremental_sync=False,
        read_only=False,
    )

    with pytest.raises(ConnectorContractError, match="read-only"):
        validate_accounting_snapshot(capabilities, accounting_snapshot())


def test_accounting_contract_rejects_records_marked_unavailable() -> None:
    snapshot = replace(
        accounting_snapshot(),
        available_datasets=frozenset({DatasetKind.COMPANY_PROFILE}),
    )
    capabilities = ConnectorCapabilities(
        source_system="accounting-fixture",
        datasets=frozenset(
            {DatasetKind.COMPANY_PROFILE, DatasetKind.ACCOUNT_BALANCES}
        ),
        supports_incremental_sync=False,
    )

    with pytest.raises(ConnectorContractError, match="returned as unavailable"):
        validate_accounting_snapshot(capabilities, snapshot)


def test_bank_contract_rejects_duplicate_provider_transaction_ids() -> None:
    transaction = BankTransaction(
        external_id="transaction-1",
        account_external_id="account-1",
        booking_date=date(2026, 7, 19),
        value_date=date(2026, 7, 19),
        direction=BankTransactionDirection.CREDIT,
        amount=Decimal("10.00"),
        currency="GEL",
        description="Fixture",
    )
    batch = BankSynchronizationBatch(
        source_system="bank-fixture",
        captured_at=CAPTURED_AT,
        available=True,
        statements=(
            BankStatement(
                statement_id="statement-1",
                account_external_id="account-1",
                period_start=date(2026, 7, 19),
                period_end=date(2026, 7, 19),
                opening_balance=None,
                closing_balance=None,
                transactions=(transaction, transaction),
            ),
        ),
    )
    capabilities = BankConnectorCapabilities(
        source_system="bank-fixture",
        supported_formats=frozenset({"fixture"}),
        supports_incremental_sync=False,
    )

    with pytest.raises(ConnectorContractError, match="Duplicate bank transaction"):
        validate_bank_batch(capabilities, batch)
