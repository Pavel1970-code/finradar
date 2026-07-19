from datetime import date
from typing import Protocol

from finradar.application.analytical_service import AnalyticalResult


class FiscalAnalysisRecorder(Protocol):
    def record(
        self,
        result: AnalyticalResult,
        *,
        analysis_date: date,
        horizon_days: int,
        synchronization_run_id: str | None,
    ) -> str: ...

