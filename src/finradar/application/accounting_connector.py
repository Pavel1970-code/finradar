from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from finradar.domain.financial_snapshot import DatasetKind, FinancialSnapshot


@dataclass(frozen=True, slots=True)
class ConnectorCapabilities:
    source_system: str
    datasets: frozenset[DatasetKind]
    supports_incremental_sync: bool


@dataclass(frozen=True, slots=True)
class SynchronizationRequest:
    since: datetime | None = None


class AccountingConnector(Protocol):
    def capabilities(self) -> ConnectorCapabilities: ...

    def test_connection(self) -> None: ...

    def synchronize(self, request: SynchronizationRequest) -> FinancialSnapshot: ...

