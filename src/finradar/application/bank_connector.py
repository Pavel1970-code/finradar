from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from finradar.domain.banking import BankSynchronizationBatch


@dataclass(frozen=True, slots=True)
class BankConnectorCapabilities:
    source_system: str
    supported_formats: frozenset[str]
    supports_incremental_sync: bool
    read_only: bool = True


@dataclass(frozen=True, slots=True)
class BankSynchronizationRequest:
    since: datetime | None = None
    cursor: str | None = None


class BankConnector(Protocol):
    def capabilities(self) -> BankConnectorCapabilities: ...

    def test_connection(self) -> None: ...

    def synchronize(self, request: BankSynchronizationRequest) -> BankSynchronizationBatch: ...


class BankSynchronizationRecorder(Protocol):
    def record(self, batch: BankSynchronizationBatch) -> str: ...
