import json
import os
import threading
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QFrame, QLabel, QPushButton
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from finradar.application.fiscal_rules import ActiveFiscalRuleSet
from finradar.application.demo_mvp import DemoMvpController
from finradar.application.fiscal_comparison import (
    FiscalComparisonStatus,
    compare_fiscal_rules,
)
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
from finradar.domain.fiscal_consequences import ConsequenceStatus
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
from finradar.infrastructure.models import FiscalAnalysisRun, SynchronizationRun
from finradar.infrastructure.fiscal_rule_registry import SqlAlchemyFiscalRuleRegistry
from finradar.infrastructure.synchronization_history import (
    SqlAlchemySynchronizationHistory,
)
from finradar.ui.main_window import BalanceChart, ForecastUiState, MainWindow


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

    assert scenario.version == 2
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
    receivable = next(
        event
        for event in first.snapshot.events
        if event.external_id == "fictional-planned-receipt-001"
    )
    assert receivable.counterparty is not None
    assert receivable.counterparty.name == "ООО «Демо Покупатель Петя»"
    assert receivable.payment_basis is not None
    assert receivable.payment_basis.document_date == date(2026, 7, 1)


@pytest.mark.parametrize(
    "scenario_id",
    [
        "base_cash_gap",
        "missing_recent_data",
        "fiscal_change_and_delay",
        "georgia_vat_pilot",
    ],
)
def test_every_demo_scenario_matches_its_golden_contract(scenario_id: str) -> None:
    scenario = DemoScenarioRepository().load(scenario_id)
    facade = ForecastApplicationFacade(
        ScenarioAccountingConnector(scenario),
        configuration=ForecastRunConfiguration(
            as_of=scenario.as_of,
            horizon_days=scenario.horizon_days,
            stress_overdue_days=scenario.stress_overdue_days,
        ),
        rule_provider=lambda: scenario.fiscal_rules,
        baseline_rule_provider=(
            (lambda: scenario.baseline_fiscal_rules)
            if scenario.baseline_fiscal_rules is not None
            else None
        ),
        bank_connector=ScenarioBankConnector(scenario),
        violation_events=scenario.violation_events,
    )

    outcome = facade.run()
    expected = scenario.expected

    assert outcome.readiness.status.value == expected.readiness_status
    assert tuple(item.code for item in outcome.readiness.issues) == expected.issue_codes
    assert outcome.forecast is not None
    assert outcome.forecast.opening_balance == expected.opening_balance
    assert outcome.forecast.closing_balance == expected.closing_balance
    assert outcome.forecast.minimum_balance == expected.minimum_balance
    assert outcome.forecast.first_gap_date == expected.first_gap_date
    assert outcome.forecast.required_funding == expected.required_funding
    assert outcome.stress_forecast is not None
    assert outcome.stress_forecast.minimum_balance == expected.stress_minimum_balance
    assert outcome.bank_reconciliation is not None
    assert outcome.bank_reconciliation.matched_count == expected.bank_matched_count
    assert outcome.bank_reconciliation.missing_count == expected.bank_missing_count
    obligations = tuple(
        item.calculation.obligation
        for item in outcome.rule_analyses
        if item.calculation.obligation is not None
    )
    assert len(obligations) == 1
    assert obligations[0].amount == expected.fiscal_obligation_amount
    calculated_penalties = sum(
        (
            item.amount
            for item in outcome.consequences
            if item.consequence_type == "late_payment_penalty"
            and item.status is ConsequenceStatus.CALCULATED
            and item.amount is not None
        ),
        Decimal("0.00"),
    )
    contingent_fines = sum(
        (
            item.amount
            for item in outcome.consequences
            if item.consequence_type == "fine"
            and item.status is ConsequenceStatus.CONTINGENT
            and item.amount is not None
        ),
        Decimal("0.00"),
    )
    assert calculated_penalties == expected.calculated_penalty_amount
    assert contingent_fines == expected.contingent_fine_amount

    if expected.comparison is None:
        assert outcome.fiscal_comparison is None
    else:
        comparison = outcome.fiscal_comparison
        golden = expected.comparison
        assert comparison is not None
        assert comparison.status is FiscalComparisonStatus.RESOLVED
        assert comparison.baseline is not None
        assert comparison.current is not None
        assert comparison.baseline.rate == golden.baseline_rate
        assert comparison.current.rate == golden.current_rate
        assert (
            comparison.baseline.obligation_amount
            == golden.baseline_obligation_amount
        )
        assert comparison.current.obligation_amount == golden.current_obligation_amount
        assert (
            comparison.baseline.forecast.minimum_balance
            == golden.baseline_minimum_balance
        )
        assert (
            comparison.current.forecast.minimum_balance
            == golden.current_minimum_balance
        )
        assert (
            comparison.baseline.forecast.first_gap_date
            == golden.baseline_first_gap_date
        )
        assert (
            comparison.current.forecast.first_gap_date
            == golden.current_first_gap_date
        )
        assert comparison.obligation_delta == golden.obligation_delta
        assert comparison.minimum_balance_delta == golden.minimum_balance_delta
        assert comparison.required_funding_delta == golden.required_funding_delta


def test_fiscal_comparison_is_unresolved_when_metric_is_missing() -> None:
    scenario = DemoScenarioRepository().load("fiscal_change_and_delay")
    snapshot = replace(scenario.accounting_snapshot, metrics=())
    assert scenario.baseline_fiscal_rules is not None

    comparison = compare_fiscal_rules(
        snapshot,
        baseline_rules=scenario.baseline_fiscal_rules,
        current_rules=scenario.fiscal_rules,
        as_of=scenario.as_of,
        horizon_days=scenario.horizon_days,
    )

    assert comparison.status is FiscalComparisonStatus.UNRESOLVED
    assert comparison.obligation_delta is None


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
    assert window.findChild(BalanceChart, "balanceChart").property("pointCount") == 30
    assert window.findChildren(QLabel, "paymentAmount")
    assert window.findChild(QLabel, "lastCalculated") is not None


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


def test_demo_controller_and_window_run_selected_scenarios(tmp_path: Path, qtbot) -> None:
    controller = DemoMvpController(_session_factory(tmp_path))
    options = controller.options()
    window = MainWindow(
        horizon_days=30,
        forecast_runner=controller.run,
        demo_scenarios=tuple((item.scenario_id, item.title) for item in options),
        initial_scenario_id="base_cash_gap",
        demo_notice="Все данные вымышлены.",
        demo_notices={item.scenario_id: item.notice for item in options},
    )
    qtbot.addWidget(window)
    window.show()
    selector = window.findChild(QComboBox, "scenarioSelector")

    selector.setCurrentIndex(selector.findData("missing_recent_data"))
    assert window.state is ForecastUiState.IDLE
    qtbot.mouseClick(
        window.findChild(QPushButton, "forecastButton"),
        Qt.MouseButton.LeftButton,
    )
    qtbot.waitUntil(lambda: window.state is ForecastUiState.RESULT, timeout=5000)
    qtbot.waitUntil(lambda: window._worker is None, timeout=5000)
    texts = "\n".join(label.text() for label in window.findChildren(QLabel))
    assert "последние 5 дней" in texts
    assert "отсутствуют банковские операции: 1" in texts
    assert "не указан контрагент" in texts
    assert "не указан документ-основание" in texts
    assert "Запись источника" not in texts
    assert "demo-accounting" not in texts

    selector = window.findChild(QComboBox, "scenarioSelector")
    selector.setCurrentIndex(selector.findData("fiscal_change_and_delay"))
    qtbot.mouseClick(
        window.findChild(QPushButton, "forecastButton"),
        Qt.MouseButton.LeftButton,
    )
    qtbot.waitUntil(lambda: window.state is ForecastUiState.RESULT, timeout=5000)
    qtbot.waitUntil(lambda: window._worker is None, timeout=5000)
    texts = "\n".join(label.text() for label in window.findChildren(QLabel))
    assert "Ставка: было 5%, стало 7%" in texts
    assert "+402.00 GEL" in texts
    assert "Штраф: 300.00 GEL" in texts
    metric_values = window.findChildren(QLabel, "metricValue")
    assert metric_values[2].text() == "-1,404.50 GEL"
    qtbot.mouseClick(
        window.findChild(QPushButton, "stressForecastButton"),
        Qt.MouseButton.LeftButton,
    )
    metric_values = window.findChildren(QLabel, "metricValue")
    assert metric_values[2].text() == "-1,709.00 GEL"
    assert window.findChild(BalanceChart, "balanceChart").property(
        "minimumBalance"
    ) == "-1709.00"
    assert len(window.findChildren(QFrame, "taxCalendarRow")) == 1
    texts = "\n".join(label.text() for label in window.findChildren(QLabel))
    assert "Частично оплачено: 500.00 GEL" in texts

    selector = window.findChild(QComboBox, "scenarioSelector")
    selector.setCurrentIndex(selector.findData("georgia_vat_pilot"))
    texts = "\n".join(label.text() for label in window.findChildren(QLabel))
    assert "Ставка, отчётный период и срок уплаты НДС" in texts
    qtbot.mouseClick(
        window.findChild(QPushButton, "forecastButton"),
        Qt.MouseButton.LeftButton,
    )
    qtbot.waitUntil(lambda: window.state is ForecastUiState.RESULT, timeout=5000)
    qtbot.waitUntil(lambda: window._worker is None, timeout=5000)
    texts = "\n".join(label.text() for label in window.findChildren(QLabel))
    assert "Начисленный НДС со стандартного облагаемого оборота: 3,600.00 GEL" in texts
    assert "Вычитаемый входной НДС: -1,100.00 GEL" in texts
    assert "Итоговая налоговая позиция: 2,500.00 GEL" in texts
    assert "Налоговый кодекс Грузии, статьи 166–168 и 181" in texts


def test_base_calendar_shows_debtors_payees_documents_and_tax_details(qtbot) -> None:
    scenario = DemoScenarioRepository().load("base_cash_gap")
    facade = ForecastApplicationFacade(
        ScenarioAccountingConnector(scenario),
        configuration=ForecastRunConfiguration(
            as_of=scenario.as_of,
            horizon_days=scenario.horizon_days,
            stress_overdue_days=scenario.stress_overdue_days,
        ),
        rule_provider=lambda: scenario.fiscal_rules,
        bank_connector=ScenarioBankConnector(scenario),
    )
    window = MainWindow(
        analysis=facade.run(),
        horizon_days=scenario.horizon_days,
    )
    qtbot.addWidget(window)
    window.show()

    texts = "\n".join(label.text() for label in window.findChildren(QLabel))

    assert "Ожидаемые поступления" in texts
    assert "Предстоящие выплаты" in texts
    assert "Налоговый календарь" in texts
    assert "ООО «Демо Покупатель Петя»" in texts
    assert "ООО «Демо Поставщик Вася»" in texts
    assert "ООО «Демо Арендодатель»" in texts
    assert "ДЕМО-НК-201" in texts
    assert "НДС за расчётный период" in texts
    assert "Налог на имущество" in texts
    assert window.findChildren(QLabel, "receiptAmount")
    assert window.findChildren(QLabel, "paymentAmount")
    assert window.findChildren(QLabel, "taxCalendarAmount")


def test_history_persists_and_opens_without_recalculation(
    tmp_path: Path,
    qtbot,
) -> None:
    session_factory = _session_factory(tmp_path)
    first_controller = DemoMvpController(session_factory)
    outcome = first_controller.run("base_cash_gap")
    assert outcome.forecast is not None

    restarted_controller = DemoMvpController(session_factory)
    items = restarted_controller.history()

    assert len(items) == 1
    assert items[0].available
    assert items[0].scenario_id == "base_cash_gap"
    assert items[0].scenario_version == 2
    assert items[0].required_funding == outcome.forecast.required_funding

    calls = 0

    def runner(scenario_id: str):
        nonlocal calls
        calls += 1
        return restarted_controller.run(scenario_id)

    window = MainWindow(
        horizon_days=30,
        forecast_runner=runner,
        demo_scenarios=tuple(
            (item.scenario_id, item.title) for item in restarted_controller.options()
        ),
        initial_scenario_id="base_cash_gap",
        history_provider=restarted_controller.history,
        history_loader=restarted_controller.load_history,
    )
    qtbot.addWidget(window)
    window.show()
    button = window.findChild(QPushButton, "historyOpenButton")

    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)

    assert calls == 0
    assert window.findChild(QPushButton, "historyCloseButton") is not None
    assert window.findChild(BalanceChart, "balanceChart").property("pointCount") == 30
    texts = "\n".join(label.text() for label in window.findChildren(QLabel))
    assert "Финансовый расчёт повторно не выполнялся" in texts
    assert "ООО «Демо Орбита»" in texts
    assert "ООО «Демо Покупатель Петя»" in texts
    assert "ДЕМО-СЧ-101" in texts


def test_history_marks_failed_integrity_check_as_unavailable(tmp_path: Path) -> None:
    session_factory = _session_factory(tmp_path)
    controller = DemoMvpController(session_factory)
    controller.run("base_cash_gap")
    with session_factory() as session:
        synchronization_run_id = session.scalar(select(SynchronizationRun.id))
        assert synchronization_run_id is not None
        corrupted = FiscalAnalysisRun(
            synchronization_run_id=synchronization_run_id,
            analysis_date=date(2026, 7, 18),
            horizon_days=30,
            algorithm_version="fiscal-v1",
            rule_result_count=0,
            consequence_count=0,
            content_json="{}",
            content_hash="0" * 64,
            created_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
        )
        session.add(corrupted)
        session.commit()
        corrupted_id = corrupted.id

    items = controller.history()

    assert not items[0].available
    assert "целостности" in (items[0].error_message or "")
    with pytest.raises(ValueError, match="integrity"):
        controller.load_history(corrupted_id)


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
