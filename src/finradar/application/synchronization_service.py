from dataclasses import dataclass
from datetime import date

from finradar.application.analytical_service import RuleAnalysis, analyze_financial_risk
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
from finradar.domain.financial_snapshot import FinancialSnapshot
from finradar.domain.fiscal import PercentageFiscalRule
from finradar.domain.forecast import ForecastResult


@dataclass(frozen=True, slots=True)
class SynchronizationOutcome:
    snapshot: FinancialSnapshot
    readiness: ReadinessReport
    forecast: ForecastResult | None
    synchronization_run_id: str | None = None
    rule_analyses: tuple[RuleAnalysis, ...] = ()


def synchronize_and_forecast(
    connector: AccountingConnector,
    *,
    as_of: date,
    horizon_days: int = 30,
    recorder: SynchronizationRecorder | None = None,
    fiscal_rules: tuple[PercentageFiscalRule, ...] = (),
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

    analytical_result = analyze_financial_risk(
        snapshot,
        fiscal_rules,
        as_of=as_of,
        horizon_days=horizon_days,
    )

    return SynchronizationOutcome(
        snapshot=snapshot,
        readiness=readiness,
        forecast=analytical_result.forecast,
        synchronization_run_id=synchronization_run_id,
        rule_analyses=analytical_result.rule_analyses,
    )
