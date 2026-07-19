from finradar.application.accounting_connector import (
    ConnectorCapabilities,
    SynchronizationRequest,
)
from finradar.application.bank_connector import (
    BankConnectorCapabilities,
    BankSynchronizationRequest,
)
from finradar.demo.scenario import DemoScenario
from finradar.domain.banking import BankSynchronizationBatch
from finradar.domain.financial_snapshot import DatasetKind, FinancialSnapshot


class ScenarioAccountingConnector:
    """Read-only accounting adapter backed by a bundled fictional scenario."""

    def __init__(self, scenario: DemoScenario) -> None:
        self._scenario = scenario

    def capabilities(self) -> ConnectorCapabilities:
        datasets = self._scenario.accounting_snapshot.available_datasets - {
            DatasetKind.BANK_TRANSACTIONS
        }
        return ConnectorCapabilities(
            source_system=self._scenario.accounting_snapshot.source_system,
            datasets=frozenset(datasets),
            supports_incremental_sync=False,
        )

    def test_connection(self) -> None:
        return None

    def synchronize(self, request: SynchronizationRequest) -> FinancialSnapshot:
        if request.cursor is not None or request.since is not None:
            raise ValueError("Demo accounting scenarios do not support incremental sync.")
        return self._scenario.accounting_snapshot


class ScenarioBankConnector:
    """Read-only bank adapter backed by a bundled fictional scenario."""

    def __init__(self, scenario: DemoScenario) -> None:
        if scenario.bank_batch is None:
            raise ValueError("The demo scenario does not contain bank data.")
        self._batch = scenario.bank_batch

    def capabilities(self) -> BankConnectorCapabilities:
        return BankConnectorCapabilities(
            source_system=self._batch.source_system,
            supported_formats=frozenset({"finradar-demo-scenario-v1"}),
            supports_incremental_sync=False,
        )

    def test_connection(self) -> None:
        return None

    def synchronize(self, request: BankSynchronizationRequest) -> BankSynchronizationBatch:
        if request.cursor is not None or request.since is not None:
            raise ValueError("Demo bank scenarios do not support incremental sync.")
        return self._batch
