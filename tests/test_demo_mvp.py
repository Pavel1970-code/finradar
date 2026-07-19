import json
import os
import threading
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from finradar.application.fiscal_rules import ActiveFiscalRuleSet
from finradar.application.forecast_facade import (
    ForecastApplicationFacade,
    ForecastRunConfiguration,
)
from finradar.application.synchronization_service import synchronize_and_forecast
from finradar.demo.scenario import (
    DemoScenarioError,
    DemoScenarioRepository,
)
from finradar.domain.data_readiness import ReadinessStatus
from finradar.infrastructure.bank_synchronization_history import (
    SqlAlchemyBankSynchronizationHistory,
)
from finradar.infrastructure.connectors.demo import DemoAccountingConnector
from finradar.infrastructure.connectors.scenario import (
    ScenarioAccountingConnector,
    ScenarioBankConnector,
)
from finradar.infrastructure.database import migrate_database
from finradar.infrastructure.demo_fiscal_rules import DemoFiscalRuleBootstrapper
from finradar.infrastructure.fiscal_analysis_history import (
    SqlAlchemyFiscalAnalysisHistory,
)
from finradar.infrastructure.fiscal_rule_registry import SqlAlchemyFiscalRuleRegistry
from finradar.infrastructure.synchronization_history import (
    SqlAlchemySynchronizationHistory,
)
from finradar.ui.main_window import ForecastUiState, MainWindow


def _session_factory(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'demo-mvp.db'}")
    migrate_database(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _in_memory_outcome():
    return synchronize_and_forecast(
        DemoAccountingConnector(as_of=date(2026, 7, 18)),
        as_of=date(2026, 7, 18),
    )


def test_bundled_base_scenario_is_versioned_and_checksummed(tmp_path: Path) -> None:
    scenario = DemoScenarioRepository().load("base_cash_gap")

    assert scenario.version == 1
    assert scenario.horizon_days == 30
    assert "вымышлен" in scenario.fictional_notice.lower()

    source = (
        Path(__file__).parents[1]
        / "src"
        / "finradar"
        / "demo"
        / "scenarios"
        / "base_cash_gap.json"
    )
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["payload"]["accounting"]["balances"][0]["amount"] = "999999.00"
    (tmp_path / "base_cash_gap.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.raises(DemoScenarioError, match="integrity"):
        DemoScenarioRepository(tmp_path).load("base_cash_gap")


def test_base_scenario_matches_golden_result_and_records_audit_history(
    tmp_path: Path,
) -> None:
    scenario = DemoScenarioRepository().load("base_cash_gap")
    session_factory = _session_factory(tmp_path)
    registry = SqlAlchemyFiscalRuleRegistry(session_factory)
    bootstrapper = DemoFiscalRuleBootstrapper(registry)
    facade = ForecastApplicationFacade(
        ScenarioAccountingConnector(scenario),
        configuration=ForecastRunConfiguration(
            as_of=scenario.as_of,
            horizon_days=scenario.horizon_days,
            stress_overdue_days=scenario.stress_overdue_days,
        ),
        rule_provider=lambda: bootstrapper.ensure(scenario.fiscal_rules),
        bank_connector=ScenarioBankConnector(scenario),
        synchronization_recorder=SqlAlchemySynchronizationHistory(session_factory),
        bank_recorder=SqlAlchemyBankSynchronizationHistory(session_factory),
        analysis_recorder=SqlAlchemyFiscalAnalysisHistory(session_factory),
        violation_events=scenario.violation_events,
    )

    first = facade.run()
    second = facade.run()
    expected = scenario.expected

    assert first.readiness.status.value == expected.readiness_status
    assert first.forecast is not None
    assert first.forecast.opening_balance == expected.opening_balance
    assert first.forecast.closing_balance == expected.closing_balance
    assert first.forecast.minimum_balance == expected.minimum_balance
    assert first.forecast.first_gap_date == expected.first_gap_date
    assert first.forecast.required_funding == expected.required_funding
    assert first.stress_forecast is not None
    assert first.stress_forecast.minimum_balance == expected.stress_minimum_balance
    obligation = first.rule_analyses[0].calculation.obligation
    assert obligation is not None
    assert obligation.amount == expected.fiscal_obligation_amount
    assert first.bank_reconciliation is not None
    assert first.bank_reconciliation.matched_count == 2
    assert first.bank_reconciliation.missing_count == 0
    assert first.synchronization_run_id is not None
    assert first.bank_synchronization_run_id is not None
    assert first.fiscal_analysis_run_id is not None
    assert second.forecast == first.forecast
    assert second.synchronization_run_id != first.synchronization_run_id


def test_forecast_window_runs_once_and_replaces_idle_state(qtbot) -> None:
    outcome = _in_memory_outcome()
    release = threading.Event()
    calls = 0

    def runner():
        nonlocal calls
        calls += 1
        release.wait(timeout=2)
        return outcome

    window = MainWindow(horizon_days=30, forecast_runner=runner)
    qtbot.addWidget(window)
    window.show()
    button = window.findChild(QPushButton, "forecastButton")

    assert window.state is ForecastUiState.IDLE
    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: window.state is ForecastUiState.RUNNING)
    assert not window.findChild(QPushButton, "forecastButton").isEnabled()
    qtbot.mouseClick(
        window.findChild(QPushButton, "forecastButton"),
        Qt.MouseButton.LeftButton,
    )
    release.set()
    qtbot.waitUntil(lambda: window.state is ForecastUiState.RESULT)
    qtbot.waitUntil(lambda: window._worker is None)

    assert calls == 1
    assert window.findChild(QPushButton, "forecastButton").text() == "Обновить прогноз"


def test_forecast_window_allows_retry_after_error(qtbot) -> None:
    outcome = _in_memory_outcome()
    attempts = 0

    def runner():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ConnectionError("Вымышленный источник временно недоступен")
        return outcome

    window = MainWindow(horizon_days=30, forecast_runner=runner)
    qtbot.addWidget(window)
    window.show()

    qtbot.mouseClick(
        window.findChild(QPushButton, "forecastButton"),
        Qt.MouseButton.LeftButton,
    )
    qtbot.waitUntil(lambda: window.state is ForecastUiState.ERROR)
    qtbot.waitUntil(lambda: window._worker is None)
    qtbot.mouseClick(
        window.findChild(QPushButton, "forecastButton"),
        Qt.MouseButton.LeftButton,
    )
    qtbot.waitUntil(lambda: window.state is ForecastUiState.RESULT)
    qtbot.waitUntil(lambda: window._worker is None)

    assert attempts == 2


def test_facade_rejects_invalid_horizon() -> None:
    with pytest.raises(ValueError, match="horizon"):
        ForecastRunConfiguration(as_of=date(2026, 7, 18), horizon_days=0)


def test_facade_can_run_without_bank_or_persistent_recorders() -> None:
    facade = ForecastApplicationFacade(
        DemoAccountingConnector(as_of=date(2026, 7, 18)),
        configuration=ForecastRunConfiguration(as_of=date(2026, 7, 18)),
        rule_provider=ActiveFiscalRuleSet,
    )

    outcome = facade.run()

    assert outcome.readiness.status is ReadinessStatus.READY
    assert outcome.forecast is not None
    assert outcome.forecast.required_funding == Decimal("500.00")
