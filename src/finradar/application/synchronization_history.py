from typing import Protocol

from finradar.domain.data_readiness import ReadinessReport
from finradar.domain.financial_snapshot import FinancialSnapshot


class SynchronizationRecorder(Protocol):
    def record(
        self,
        snapshot: FinancialSnapshot,
        readiness: ReadinessReport,
    ) -> str: ...

