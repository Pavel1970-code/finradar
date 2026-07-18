from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from finradar.application.accounting_connector import (
    AccountingConnector,
    SynchronizationRequest,
)
from finradar.application.synchronization_history import SynchronizationRecorder
from finradar.domain.data_readiness import (
    ReadinessReport,
    ReadinessStatus,
    assess_forecast_readiness,
)
from finradar.domain.financial_snapshot import (
    FinancialDirection,
    FinancialEventKind,
    FinancialSnapshot,
)
from finradar.domain.forecast import ForecastEvent, ForecastResult, calculate_cash_forecast


@dataclass(frozen=True, slots=True)
class SynchronizationOutcome:
    snapshot: FinancialSnapshot
    readiness: ReadinessReport
    forecast: ForecastResult | None
    synchronization_run_id: str | None = None


def synchronize_and_forecast(
    connector: AccountingConnector,
    *,
    as_of: date,
    horizon_days: int = 30,
    recorder: SynchronizationRecorder | None = None,
) -> SynchronizationOutcome:
    connector.test_connection()
    capabilities = connector.capabilities()
    snapshot = connector.synchronize(SynchronizationRequest())

    if snapshot.source_system != capabilities.source_system:
        raise ValueError("Connector returned a snapshot for another source system.")

    undeclared_datasets = snapshot.available_datasets - capabilities.datasets
    if undeclared_datasets:
        raise ValueError("Connector returned datasets that it did not declare.")

    readiness = assess_forecast_readiness(snapshot, as_of=as_of)
    synchronization_run_id = (
        recorder.record(snapshot, readiness) if recorder is not None else None
    )
    if readiness.status is ReadinessStatus.BLOCKED:
        return SynchronizationOutcome(
            snapshot=snapshot,
            readiness=readiness,
            forecast=None,
            synchronization_run_id=synchronization_run_id,
        )

    opening_balance = sum(
        (balance.amount for balance in snapshot.balances),
        start=Decimal("0.00"),
    )
    events = (
        ForecastEvent(
            due_date=event.due_date,
            amount=event.amount,
            is_inflow=event.direction is FinancialDirection.INFLOW,
            reference=event.external_id,
        )
        for event in snapshot.events
        if event.kind is FinancialEventKind.PLANNED
    )
    forecast = calculate_cash_forecast(
        opening_balance=opening_balance,
        start_date=as_of,
        horizon_days=horizon_days,
        events=events,
    )

    return SynchronizationOutcome(
        snapshot=snapshot,
        readiness=readiness,
        forecast=forecast,
        synchronization_run_id=synchronization_run_id,
    )
