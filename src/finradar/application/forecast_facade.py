from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date

from finradar.application.accounting_connector import AccountingConnector
from finradar.application.bank_connector import (
    BankConnector,
    BankSynchronizationRecorder,
)
from finradar.application.fiscal_analysis_history import FiscalAnalysisRecorder
from finradar.application.fiscal_comparison import compare_fiscal_rules
from finradar.application.fiscal_rules import ActiveFiscalRuleSet
from finradar.application.synchronization_history import SynchronizationRecorder
from finradar.application.synchronization_service import (
    SynchronizationOutcome,
    synchronize_and_forecast,
)
from finradar.domain.fiscal_consequences import ViolationEvent


FiscalRuleProvider = Callable[[], ActiveFiscalRuleSet]


@dataclass(frozen=True, slots=True)
class ForecastRunConfiguration:
    as_of: date
    horizon_days: int = 30
    stress_overdue_days: int = 0

    def __post_init__(self) -> None:
        if not 1 <= self.horizon_days <= 366:
            raise ValueError("Forecast horizon must be between 1 and 366 days.")
        if not 0 <= self.stress_overdue_days <= 366:
            raise ValueError("Stress overdue days must be between 0 and 366.")


class ForecastApplicationFacade:
    """Single application use case used by the desktop forecast action."""

    def __init__(
        self,
        accounting_connector: AccountingConnector,
        *,
        configuration: ForecastRunConfiguration,
        rule_provider: FiscalRuleProvider,
        baseline_rule_provider: FiscalRuleProvider | None = None,
        bank_connector: BankConnector | None = None,
        synchronization_recorder: SynchronizationRecorder | None = None,
        bank_recorder: BankSynchronizationRecorder | None = None,
        analysis_recorder: FiscalAnalysisRecorder | None = None,
        violation_events: tuple[ViolationEvent, ...] = (),
    ) -> None:
        self._accounting_connector = accounting_connector
        self._configuration = configuration
        self._rule_provider = rule_provider
        self._baseline_rule_provider = baseline_rule_provider
        self._bank_connector = bank_connector
        self._synchronization_recorder = synchronization_recorder
        self._bank_recorder = bank_recorder
        self._analysis_recorder = analysis_recorder
        self._violation_events = violation_events

    @property
    def configuration(self) -> ForecastRunConfiguration:
        return self._configuration

    def run(self) -> SynchronizationOutcome:
        rules = self._rule_provider()
        outcome = synchronize_and_forecast(
            self._accounting_connector,
            as_of=self._configuration.as_of,
            horizon_days=self._configuration.horizon_days,
            recorder=self._synchronization_recorder,
            fiscal_rules=rules.obligation_rules,
            penalty_rules=rules.penalty_rules,
            fine_rules=rules.fine_rules,
            violation_events=self._violation_events,
            stress_overdue_days=self._configuration.stress_overdue_days,
            analysis_recorder=self._analysis_recorder,
            bank_connector=self._bank_connector,
            bank_recorder=self._bank_recorder,
        )
        if self._baseline_rule_provider is None or outcome.forecast is None:
            return outcome
        comparison = compare_fiscal_rules(
            outcome.snapshot,
            baseline_rules=self._baseline_rule_provider(),
            current_rules=rules,
            as_of=self._configuration.as_of,
            horizon_days=self._configuration.horizon_days,
            violation_events=self._violation_events,
        )
        return replace(outcome, fiscal_comparison=comparison)
