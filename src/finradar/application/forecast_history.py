from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol

from finradar.domain.forecast import ForecastEvent, ForecastResult
from finradar.domain.financial_snapshot import FinancialEvent


@dataclass(frozen=True, slots=True)
class ForecastHistoryItem:
    analysis_run_id: str
    created_at: datetime
    analysis_date: date
    horizon_days: int
    company_name: str
    currency: str
    readiness_status: str
    scenario_id: str | None
    scenario_version: int | None
    first_gap_date: date | None
    minimum_balance: Decimal | None
    required_funding: Decimal | None
    available: bool
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class HistoricalFiscalObligation:
    title: str
    amount: Decimal
    outstanding_amount: Decimal
    currency: str
    due_date: date
    recipient_name: str
    period_start: date | None
    period_end: date | None


@dataclass(frozen=True, slots=True)
class HistoricalFiscalConsequence:
    consequence_type: str
    status: str
    amount: Decimal | None
    currency: str
    assessment_date: date


@dataclass(frozen=True, slots=True)
class ForecastHistoryDetails:
    item: ForecastHistoryItem
    forecast: ForecastResult
    stress_forecast: ForecastResult
    forecast_events: tuple[ForecastEvent, ...]
    stress_forecast_events: tuple[ForecastEvent, ...]
    payment_events: tuple[FinancialEvent, ...]
    obligations: tuple[HistoricalFiscalObligation, ...]
    consequences: tuple[HistoricalFiscalConsequence, ...]


class ForecastHistoryReader(Protocol):
    def list_recent(self, *, limit: int = 20) -> tuple[ForecastHistoryItem, ...]: ...

    def load_details(self, analysis_run_id: str) -> ForecastHistoryDetails: ...
