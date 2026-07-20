from dataclasses import dataclass
from datetime import date

from finradar.application.analytical_service import RuleAnalysis, analyze_financial_risk
from finradar.application.fiscal_analysis_history import FiscalAnalysisRecorder
from finradar.application.fiscal_comparison import FiscalComparison
from finradar.application.accounting_connector import (
    AccountingConnector,
    SynchronizationRequest,
)
from finradar.application.bank_connector import (
    BankConnector,
    BankSynchronizationRecorder,
    BankSynchronizationRequest,
)
from finradar.application.bank_reconciliation import (
    BankReconciliationReport,
    attach_bank_reconciliation,
    reconcile_bank_batch,
)
from finradar.application.integration_sdk import (
    validate_accounting_snapshot,
    validate_bank_batch,
)
from finradar.application.synchronization_history import SynchronizationRecorder
from finradar.domain.data_readiness import (
    ReadinessReport,
    ReadinessStatus,
    assess_forecast_readiness,
)
from finradar.domain.financial_snapshot import FinancialSnapshot
from finradar.domain.fiscal import PercentageFiscalRule
from finradar.domain.fiscal_consequences import (
    FineRule,
    FiscalConsequence,
    LatePaymentPenaltyRule,
    ViolationEvent,
)
from finradar.domain.forecast import ForecastEvent, ForecastResult


@dataclass(frozen=True, slots=True)
class SynchronizationOutcome:
    snapshot: FinancialSnapshot
    readiness: ReadinessReport
    forecast: ForecastResult | None
    synchronization_run_id: str | None = None
    rule_analyses: tuple[RuleAnalysis, ...] = ()
    stress_forecast: ForecastResult | None = None
    consequences: tuple[FiscalConsequence, ...] = ()
    fiscal_analysis_run_id: str | None = None
    bank_reconciliation: BankReconciliationReport | None = None
    bank_synchronization_run_id: str | None = None
    fiscal_comparison: FiscalComparison | None = None
    forecast_events: tuple[ForecastEvent, ...] = ()
    stress_forecast_events: tuple[ForecastEvent, ...] = ()


def synchronize_and_forecast(
    connector: AccountingConnector,
    *,
    as_of: date,
    horizon_days: int = 30,
    recorder: SynchronizationRecorder | None = None,
    fiscal_rules: tuple[PercentageFiscalRule, ...] = (),
    penalty_rules: tuple[LatePaymentPenaltyRule, ...] = (),
    fine_rules: tuple[FineRule, ...] = (),
    violation_events: tuple[ViolationEvent, ...] = (),
    stress_overdue_days: int = 0,
    analysis_recorder: FiscalAnalysisRecorder | None = None,
    synchronization_request: SynchronizationRequest | None = None,
    bank_connector: BankConnector | None = None,
    bank_recorder: BankSynchronizationRecorder | None = None,
    bank_request: BankSynchronizationRequest | None = None,
) -> SynchronizationOutcome:
    connector.test_connection()
    capabilities = connector.capabilities()
    snapshot = validate_accounting_snapshot(
        capabilities,
        connector.synchronize(synchronization_request or SynchronizationRequest()),
    )
    bank_reconciliation = None
    bank_synchronization_run_id = None
    if bank_connector is not None:
        bank_connector.test_connection()
        bank_capabilities = bank_connector.capabilities()
        bank_batch = validate_bank_batch(
            bank_capabilities,
            bank_connector.synchronize(bank_request or BankSynchronizationRequest()),
        )
        bank_synchronization_run_id = (
            bank_recorder.record(bank_batch) if bank_recorder is not None else None
        )
        bank_reconciliation = reconcile_bank_batch(snapshot, bank_batch, as_of=as_of)
        snapshot = attach_bank_reconciliation(
            snapshot,
            bank_batch,
            bank_reconciliation,
            synchronization_run_id=bank_synchronization_run_id,
        )

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
            bank_reconciliation=bank_reconciliation,
            bank_synchronization_run_id=bank_synchronization_run_id,
        )

    analytical_result = analyze_financial_risk(
        snapshot,
        fiscal_rules,
        as_of=as_of,
        horizon_days=horizon_days,
        penalty_rules=penalty_rules,
        fine_rules=fine_rules,
        violation_events=violation_events,
        stress_overdue_days=stress_overdue_days,
    )
    fiscal_analysis_run_id = (
        analysis_recorder.record(
            analytical_result,
            analysis_date=as_of,
            horizon_days=horizon_days,
            synchronization_run_id=synchronization_run_id,
        )
        if analysis_recorder is not None
        else None
    )

    return SynchronizationOutcome(
        snapshot=snapshot,
        readiness=readiness,
        forecast=analytical_result.forecast,
        synchronization_run_id=synchronization_run_id,
        rule_analyses=analytical_result.rule_analyses,
        stress_forecast=analytical_result.stress_forecast,
        consequences=analytical_result.consequences,
        fiscal_analysis_run_id=fiscal_analysis_run_id,
        bank_reconciliation=bank_reconciliation,
        bank_synchronization_run_id=bank_synchronization_run_id,
        forecast_events=analytical_result.forecast_events,
        stress_forecast_events=analytical_result.stress_forecast_events,
    )
