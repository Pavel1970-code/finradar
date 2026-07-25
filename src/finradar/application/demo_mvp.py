from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session, sessionmaker

from finradar.application.forecast_facade import (
    ForecastApplicationFacade,
    ForecastRunConfiguration,
)
from finradar.application.forecast_history import (
    ForecastHistoryDetails,
    ForecastHistoryItem,
)
from finradar.application.synchronization_service import SynchronizationOutcome
from finradar.demo.scenario import DemoScenarioRepository
from finradar.infrastructure.bank_synchronization_history import (
    SqlAlchemyBankSynchronizationHistory,
)
from finradar.infrastructure.connectors.scenario import (
    ScenarioAccountingConnector,
    ScenarioBankConnector,
)
from finradar.infrastructure.demo_fiscal_rules import DemoFiscalRuleBootstrapper
from finradar.infrastructure.fiscal_analysis_history import (
    SqlAlchemyFiscalAnalysisHistory,
)
from finradar.infrastructure.fiscal_rule_registry import SqlAlchemyFiscalRuleRegistry
from finradar.infrastructure.synchronization_history import (
    SqlAlchemySynchronizationHistory,
)


@dataclass(frozen=True, slots=True)
class DemoScenarioOption:
    scenario_id: str
    title: str
    notice: str


class DemoMvpController:
    """Application-level assembly for the bundled offline demonstration."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        repository: DemoScenarioRepository | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._repository = repository or DemoScenarioRepository()
        self._bootstrapper = DemoFiscalRuleBootstrapper(
            SqlAlchemyFiscalRuleRegistry(session_factory)
        )
        self._analysis_history = SqlAlchemyFiscalAnalysisHistory(session_factory)

    def options(self) -> tuple[DemoScenarioOption, ...]:
        return tuple(
            DemoScenarioOption(item.scenario_id, item.title, item.fictional_notice)
            for item in self._repository.list()
        )

    def history(self, *, limit: int = 20) -> tuple[ForecastHistoryItem, ...]:
        return self._analysis_history.list_recent(limit=limit)

    def load_history(self, analysis_run_id: str) -> ForecastHistoryDetails:
        return self._analysis_history.load_details(analysis_run_id)

    def run(self, scenario_id: str) -> SynchronizationOutcome:
        scenario = self._repository.load(scenario_id)
        facade = ForecastApplicationFacade(
            ScenarioAccountingConnector(scenario),
            configuration=ForecastRunConfiguration(
                as_of=scenario.as_of,
                horizon_days=scenario.horizon_days,
                stress_overdue_days=scenario.stress_overdue_days,
            ),
            rule_provider=lambda: self._bootstrapper.ensure(scenario.fiscal_rules),
            baseline_rule_provider=(
                (lambda: scenario.baseline_fiscal_rules)
                if scenario.baseline_fiscal_rules is not None
                else None
            ),
            bank_connector=(
                ScenarioBankConnector(scenario)
                if scenario.bank_batch is not None
                else None
            ),
            synchronization_recorder=SqlAlchemySynchronizationHistory(
                self._session_factory
            ),
            bank_recorder=SqlAlchemyBankSynchronizationHistory(self._session_factory),
            analysis_recorder=self._analysis_history,
            violation_events=scenario.violation_events,
        )
        return facade.run()
