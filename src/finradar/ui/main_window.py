from collections.abc import Callable
from decimal import Decimal
from enum import Enum

from PySide6.QtCore import QThread, Signal

from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QComboBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from finradar.application.synchronization_service import SynchronizationOutcome
from finradar.domain.data_readiness import ReadinessStatus
from finradar.domain.financial_snapshot import DatasetKind
from finradar.ui.forecast_view_model import (
    ForecastViewModel,
    build_forecast_view_model,
)


class ForecastUiState(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    RESULT = "result"
    ERROR = "error"


class _ForecastWorker(QThread):
    result_ready = Signal(object)
    failed = Signal(str)

    def __init__(self, runner: Callable[[], SynchronizationOutcome]) -> None:
        super().__init__()
        self._runner = runner

    def run(self) -> None:
        try:
            self.result_ready.emit(self._runner())
        except Exception as error:  # UI boundary: domain errors must not close the app.
            self.failed.emit(str(error) or type(error).__name__)


def format_money(
    amount: Decimal,
    currency: str,
) -> str:
    return f"{amount:,.2f} {currency}"


def format_signed_money(amount: Decimal, currency: str) -> str:
    sign = "+" if amount > Decimal("0.00") else ""
    return f"{sign}{amount:,.2f} {currency}"


def create_metric_card(
    caption: str,
    value: str,
    *,
    state: str = "neutral",
) -> QFrame:
    card = QFrame()
    card.setObjectName("metricCard")

    layout = QVBoxLayout(card)
    layout.setContentsMargins(22, 20, 22, 20)
    layout.setSpacing(10)

    caption_label = QLabel(caption)
    caption_label.setObjectName("metricCaption")

    value_label = QLabel(value)
    value_label.setObjectName("metricValue")
    value_label.setWordWrap(True)

    if state == "danger":
        value_label.setStyleSheet("color: #fb7185;")
    elif state == "safe":
        value_label.setStyleSheet("color: #5eead4;")

    layout.addWidget(caption_label)
    layout.addWidget(value_label)

    return card


class MainWindow(QMainWindow):
    def __init__(
        self,
        *,
        analysis: SynchronizationOutcome | None = None,
        horizon_days: int,
        forecast_runner: Callable[..., SynchronizationOutcome] | None = None,
        demo_scenarios: tuple[tuple[str, str], ...] = (),
        initial_scenario_id: str | None = None,
        demo_notice: str | None = None,
    ) -> None:
        super().__init__()

        self._analysis = analysis
        self._horizon_days = horizon_days
        self._forecast_runner = forecast_runner
        self._demo_scenarios = demo_scenarios
        self._selected_scenario_id = initial_scenario_id
        if self._selected_scenario_id is None and demo_scenarios:
            self._selected_scenario_id = demo_scenarios[0][0]
        self._demo_notice = demo_notice
        self._error_message: str | None = None
        self._worker: _ForecastWorker | None = None
        self._show_stress = False
        self._state = (
            ForecastUiState.RESULT if analysis is not None else ForecastUiState.IDLE
        )

        self.setWindowTitle("FinRadar — Financial Early Warning")
        self.resize(1200, 760)
        self.setMinimumSize(960, 640)

        self._render()
        self._apply_styles()

    @property
    def state(self) -> ForecastUiState:
        return self._state

    def start_forecast(self) -> None:
        if self._forecast_runner is None:
            return
        if self._worker is not None and self._worker.isRunning():
            return
        self._state = ForecastUiState.RUNNING
        self._error_message = None
        self._render()

        runner = self._forecast_runner
        if self._demo_scenarios:
            scenario_id = self._selected_scenario_id
            assert scenario_id is not None
            worker = _ForecastWorker(lambda: runner(scenario_id))
        else:
            worker = _ForecastWorker(runner)
        self._worker = worker
        worker.result_ready.connect(self._accept_result)
        worker.failed.connect(self._accept_error)
        worker.finished.connect(self._release_worker)
        worker.start()

    def _accept_result(self, analysis: SynchronizationOutcome) -> None:
        self._analysis = analysis
        self._show_stress = False
        self._state = ForecastUiState.RESULT
        self._error_message = None
        self._render()

    def _accept_error(self, message: str) -> None:
        self._state = ForecastUiState.ERROR
        self._error_message = message
        self._render()

    def _release_worker(self) -> None:
        worker = self._worker
        self._worker = None
        if worker is not None:
            worker.deleteLater()

    def _render(self) -> None:
        previous = self.takeCentralWidget()
        if previous is not None:
            previous.deleteLater()

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)

        content_widget = QWidget()
        content_widget.setObjectName("contentWidget")
        root_layout = QVBoxLayout(content_widget)
        root_layout.setContentsMargins(42, 34, 42, 34)
        root_layout.setSpacing(24)

        title = QLabel("FinRadar")
        title.setObjectName("title")
        root_layout.addWidget(title)

        if self._demo_notice:
            notice = QLabel(self._demo_notice)
            notice.setObjectName("demoNotice")
            notice.setWordWrap(True)
            root_layout.addWidget(notice)

        self._build_action_panel(root_layout)

        if self._state is ForecastUiState.IDLE:
            self._build_status_card(
                root_layout,
                "Прогноз ещё не рассчитан",
                "Нажмите «Дать прогноз». Приложение проверит данные, "
                "сопоставит бухгалтерские и банковские операции и выполнит расчёт.",
            )
        elif self._state is ForecastUiState.RUNNING:
            self._build_status_card(
                root_layout,
                "Выполняется расчёт",
                "Проверяем полноту данных и строим детерминированный прогноз.",
            )
        elif self._state is ForecastUiState.ERROR:
            self._build_status_card(
                root_layout,
                "Не удалось построить прогноз",
                self._error_message or "Неизвестная ошибка.",
                error=True,
            )
        else:
            assert self._analysis is not None
            view_model = build_forecast_view_model(self._analysis)
            self._build_readiness_report(root_layout, self._analysis)
            self._build_data_gaps(root_layout, view_model)
            if (
                self._analysis.forecast is None
                or self._analysis.snapshot.company is None
            ):
                self._build_empty_state(root_layout)
            else:
                self._build_dashboard(
                    root_layout,
                    self._analysis,
                    self._horizon_days,
                )
                self._build_fiscal_report(root_layout, view_model)
                self._build_comparison_report(root_layout, view_model)
                self._build_stress_report(root_layout, self._analysis)

        root_layout.addStretch()
        scroll_area.setWidget(content_widget)
        self.setCentralWidget(scroll_area)

    def _build_action_panel(self, root_layout: QVBoxLayout) -> None:
        if self._forecast_runner is None:
            return
        controls = QFrame()
        controls.setObjectName("actionPanel")
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(16, 14, 16, 14)
        controls_layout.setSpacing(14)

        if self._demo_scenarios:
            selector_label = QLabel("Демонстрационный сценарий")
            selector_label.setObjectName("controlLabel")
            selector = QComboBox()
            selector.setObjectName("scenarioSelector")
            for scenario_id, title in self._demo_scenarios:
                selector.addItem(title, scenario_id)
            selected_index = selector.findData(self._selected_scenario_id)
            if selected_index >= 0:
                selector.setCurrentIndex(selected_index)
            selector.setEnabled(self._state is not ForecastUiState.RUNNING)
            selector.currentIndexChanged.connect(self._scenario_changed)
            controls_layout.addWidget(selector_label)
            controls_layout.addWidget(selector, 1)

        button = QPushButton(
            "Обновить прогноз"
            if self._analysis is not None
            else "Дать прогноз"
        )
        button.setObjectName("forecastButton")
        button.setEnabled(self._state is not ForecastUiState.RUNNING)
        button.clicked.connect(self.start_forecast)
        controls_layout.addWidget(button)
        root_layout.addWidget(controls)

    def _scenario_changed(self, index: int) -> None:
        selector = self.sender()
        if not isinstance(selector, QComboBox) or index < 0:
            return
        scenario_id = selector.itemData(index)
        if not isinstance(scenario_id, str) or scenario_id == self._selected_scenario_id:
            return
        self._selected_scenario_id = scenario_id
        self._analysis = None
        self._show_stress = False
        self._state = ForecastUiState.IDLE
        self._error_message = None
        self._render()

    def _build_status_card(
        self,
        root_layout: QVBoxLayout,
        title: str,
        message: str,
        *,
        error: bool = False,
    ) -> None:
        card = QFrame()
        card.setObjectName("errorCard" if error else "emptyCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(26, 24, 26, 24)
        layout.setSpacing(8)

        heading = QLabel(title)
        heading.setObjectName("statusTitle")
        description = QLabel(message)
        description.setObjectName("readinessError" if error else "description")
        description.setWordWrap(True)
        layout.addWidget(heading)
        layout.addWidget(description)
        root_layout.addWidget(card)

    def _build_empty_state(
        self,
        root_layout: QVBoxLayout,
    ) -> None:
        subtitle = QLabel(
            "Прогноз пока недоступен."
        )
        subtitle.setObjectName("subtitle")

        empty_card = QFrame()
        empty_card.setObjectName("emptyCard")

        card_layout = QVBoxLayout(empty_card)
        card_layout.setContentsMargins(26, 24, 26, 24)

        message = QLabel(
            "Исправьте блокирующие пробелы, перечисленные "
            "в предварительном отчёте, и повторите синхронизацию."
        )
        message.setObjectName("description")
        message.setWordWrap(True)

        card_layout.addWidget(message)

        root_layout.addWidget(subtitle)
        root_layout.addWidget(empty_card)

    def _build_readiness_report(
        self,
        root_layout: QVBoxLayout,
        analysis: SynchronizationOutcome,
    ) -> None:
        report = analysis.readiness
        status_text = {
            ReadinessStatus.READY: "Данные готовы к анализу",
            ReadinessStatus.LIMITED: "Анализ возможен с ограничениями",
            ReadinessStatus.BLOCKED: "Анализ заблокирован",
        }[report.status]
        status_object = {
            ReadinessStatus.READY: "readinessReady",
            ReadinessStatus.LIMITED: "readinessLimited",
            ReadinessStatus.BLOCKED: "readinessBlocked",
        }[report.status]

        heading = QLabel("Предварительная проверка данных")
        heading.setObjectName("sectionTitle")
        root_layout.addWidget(heading)

        card = QFrame()
        card.setObjectName(status_object)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(24, 20, 24, 20)
        card_layout.setSpacing(10)

        status_label = QLabel(status_text)
        status_label.setObjectName("readinessStatus")
        card_layout.addWidget(status_label)

        source_label = QLabel(
            "Дата актуальности данных: "
            f"{analysis.snapshot.captured_at.strftime('%d.%m.%Y %H:%M')}"
        )
        source_label.setObjectName("readinessMeta")
        source_label.setWordWrap(True)
        card_layout.addWidget(source_label)

        if not report.issues:
            message = QLabel("Обязательные данные получены, критических пробелов нет.")
            message.setObjectName("description")
            message.setWordWrap(True)
            card_layout.addWidget(message)
        else:
            message = QLabel(
                f"Обнаружено проблем с полнотой или согласованностью данных: "
                f"{len(report.issues)}. Подробности приведены ниже."
            )
            message.setObjectName("description")
            message.setWordWrap(True)
            card_layout.addWidget(message)

        root_layout.addWidget(card)

    def _build_data_gaps(
        self,
        root_layout: QVBoxLayout,
        view_model: ForecastViewModel,
    ) -> None:
        if not view_model.data_gaps:
            return
        heading = QLabel("Каких данных не хватает или что требует проверки")
        heading.setObjectName("sectionTitle")
        root_layout.addWidget(heading)

        card = QFrame()
        card.setObjectName("detailsCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)
        for issue in view_model.data_gaps:
            marker = "Блокирует прогноз" if issue.blocking else "Ограничение"
            issue_label = QLabel(
                f"{marker}: {issue.message}\nВлияние: {issue.impact}"
            )
            issue_label.setObjectName(
                "readinessError" if issue.blocking else "readinessWarning"
            )
            issue_label.setWordWrap(True)
            layout.addWidget(issue_label)
        root_layout.addWidget(card)

    def _build_dashboard(
        self,
        root_layout: QVBoxLayout,
        analysis: SynchronizationOutcome,
        horizon_days: int,
    ) -> None:
        self._build_forecast_mode_controls(root_layout, analysis)
        result = (
            analysis.stress_forecast
            if self._show_stress and analysis.stress_forecast is not None
            else analysis.forecast
        )
        company = analysis.snapshot.company
        assert result is not None
        assert company is not None

        subtitle = QLabel(
            f"{company.name} · "
            f"Данные на {analysis.snapshot.captured_at.strftime('%d.%m.%Y')} · "
            f"{'Стресс-сценарий' if self._show_stress else 'Основной прогноз'} "
            f"на {horizon_days} дней · "
            f"Событий: {len(analysis.snapshot.events)}"
        )
        subtitle.setObjectName("subtitle")
        root_layout.addWidget(subtitle)

        metrics = QGridLayout()
        metrics.setHorizontalSpacing(16)
        metrics.setVerticalSpacing(16)

        first_gap_text = (
            result.first_gap_date.strftime("%d.%m.%Y")
            if result.first_gap_date is not None
            else "Не обнаружен"
        )

        minimum_state = (
            "danger"
            if result.minimum_balance < Decimal("0.00")
            else "safe"
        )

        gap_state = (
            "danger"
            if result.first_gap_date is not None
            else "safe"
        )

        metric_cards = [
            create_metric_card(
                "Текущий остаток",
                format_money(
                    result.opening_balance,
                    company.base_currency,
                ),
            ),
            create_metric_card(
                f"Остаток через {horizon_days} дней",
                format_money(
                    result.closing_balance,
                    company.base_currency,
                ),
            ),
            create_metric_card(
                "Минимальный баланс",
                format_money(
                    result.minimum_balance,
                    company.base_currency,
                ),
                state=minimum_state,
            ),
            create_metric_card(
                "Первый кассовый разрыв",
                first_gap_text,
                state=gap_state,
            ),
        ]

        for column, card in enumerate(metric_cards):
            metrics.addWidget(card, 0, column)
            metrics.setColumnStretch(column, 1)

        root_layout.addLayout(metrics)

        risk_card = QFrame()

        if result.first_gap_date is not None:
            risk_card.setObjectName("riskCard")

            risk_title_text = "Обнаружен риск кассового разрыва"
            risk_description_text = (
                "Для прохождения прогнозного периода требуется "
                f"дополнительное финансирование: "
                f"{format_money(result.required_funding, company.base_currency)}."
            )
        else:
            risk_card.setObjectName("safeCard")

            risk_title_text = "Кассовый разрыв не обнаружен"
            risk_description_text = (
                "На основании известных поступлений и обязательств "
                "остаток остаётся положительным."
            )

        risk_layout = QVBoxLayout(risk_card)
        risk_layout.setContentsMargins(26, 22, 26, 22)
        risk_layout.setSpacing(8)

        risk_title = QLabel(risk_title_text)
        risk_title.setObjectName("riskTitle")

        risk_description = QLabel(risk_description_text)
        risk_description.setObjectName("description")
        risk_description.setWordWrap(True)

        risk_layout.addWidget(risk_title)
        risk_layout.addWidget(risk_description)

        root_layout.addWidget(risk_card)

        audit_note = QLabel(
            "Расчёт выполнен детерминированным ядром. "
            "AI не участвует в вычислении финансовых показателей."
        )
        audit_note.setObjectName("auditNote")
        audit_note.setWordWrap(True)

        root_layout.addWidget(audit_note)

    def _build_forecast_mode_controls(
        self,
        root_layout: QVBoxLayout,
        analysis: SynchronizationOutcome,
    ) -> None:
        if (
            analysis.forecast is None
            or analysis.stress_forecast is None
            or analysis.forecast == analysis.stress_forecast
        ):
            return
        controls = QFrame()
        controls.setObjectName("modePanel")
        layout = QHBoxLayout(controls)
        layout.setContentsMargins(8, 8, 8, 8)
        primary = QPushButton("Основной прогноз")
        primary.setObjectName("primaryForecastButton")
        primary.setCheckable(True)
        primary.setChecked(not self._show_stress)
        primary.clicked.connect(lambda: self._set_forecast_mode(False))
        stress = QPushButton("Стресс-сценарий")
        stress.setObjectName("stressForecastButton")
        stress.setCheckable(True)
        stress.setChecked(self._show_stress)
        stress.clicked.connect(lambda: self._set_forecast_mode(True))
        layout.addWidget(primary)
        layout.addWidget(stress)
        layout.addStretch()
        root_layout.addWidget(controls)

    def _set_forecast_mode(self, stress: bool) -> None:
        if self._show_stress == stress:
            return
        self._show_stress = stress
        self._render()

    def _build_fiscal_report(
        self,
        root_layout: QVBoxLayout,
        view_model: ForecastViewModel,
    ) -> None:
        if not view_model.obligations and not view_model.consequences:
            return

        heading = QLabel("Налоги и возможные последствия")
        heading.setObjectName("sectionTitle")
        root_layout.addWidget(heading)
        card = QFrame()
        card.setObjectName("detailsCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        for obligation in view_model.obligations:
            rate = (obligation.rate * Decimal("100")).normalize()
            label = QLabel(
                f"{obligation.title}\n"
                f"Расчёт: {rate}% от базы — "
                f"{format_money(obligation.amount, obligation.currency)}. "
                f"Срок: {obligation.due_date.strftime('%d.%m.%Y')}. "
                "Осталось оплатить: "
                f"{format_money(obligation.outstanding_amount, obligation.currency)}."
            )
            label.setObjectName("detailText")
            label.setWordWrap(True)
            layout.addWidget(label)

        for consequence in view_model.consequences:
            amount_text = (
                format_money(consequence.amount, consequence.currency)
                if consequence.amount is not None
                else "сумма не определена"
            )
            label = QLabel(
                f"{consequence.title}: {amount_text}. {consequence.status_text}. "
                f"Дата расчёта: {consequence.assessment_date.strftime('%d.%m.%Y')}."
            )
            label.setObjectName(
                "readinessWarning" if consequence.warning else "detailText"
            )
            label.setWordWrap(True)
            layout.addWidget(label)

        note = QLabel(
            "Суммы рассчитаны по вымышленным правилам демонстрационного сценария. "
            f"Валюта представления: {view_model.currency}."
        )
        note.setObjectName("auditNote")
        note.setWordWrap(True)
        layout.addWidget(note)
        root_layout.addWidget(card)

    def _build_comparison_report(
        self,
        root_layout: QVBoxLayout,
        view_model: ForecastViewModel,
    ) -> None:
        comparison = view_model.comparison
        if comparison is None:
            return
        heading = QLabel("Было — стало — влияние на прогноз")
        heading.setObjectName("sectionTitle")
        root_layout.addWidget(heading)
        card = QFrame()
        card.setObjectName("comparisonCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        if not comparison.resolved:
            message = QLabel(
                "Сравнение невозможно: для одного из вариантов недостаточно "
                "данных для однозначного налогового расчёта."
            )
            message.setObjectName("readinessWarning")
            message.setWordWrap(True)
            layout.addWidget(message)
        else:
            assert comparison.baseline_rate is not None
            assert comparison.current_rate is not None
            assert comparison.baseline_obligation is not None
            assert comparison.current_obligation is not None
            assert comparison.baseline_funding is not None
            assert comparison.current_funding is not None
            assert comparison.obligation_delta is not None
            assert comparison.funding_delta is not None
            currency = view_model.currency
            old_rate = (comparison.baseline_rate * Decimal("100")).normalize()
            new_rate = (comparison.current_rate * Decimal("100")).normalize()
            rate_label = QLabel(
                f"Ставка: было {old_rate}%, стало {new_rate}%."
            )
            rate_label.setObjectName("comparisonTitle")
            amount_label = QLabel(
                "Обязательство: "
                f"{format_money(comparison.baseline_obligation, currency)} → "
                f"{format_money(comparison.current_obligation, currency)} "
                f"(изменение {format_signed_money(comparison.obligation_delta, currency)})."
            )
            funding_label = QLabel(
                "Требуемое финансирование: "
                f"{format_money(comparison.baseline_funding, currency)} → "
                f"{format_money(comparison.current_funding, currency)} "
                f"(изменение "
                f"{format_signed_money(comparison.funding_delta, currency)})."
            )
            for label in (rate_label, amount_label, funding_label):
                label.setWordWrap(True)
                if label.objectName() != "comparisonTitle":
                    label.setObjectName("detailText")
                layout.addWidget(label)
        root_layout.addWidget(card)

    def _build_stress_report(
        self,
        root_layout: QVBoxLayout,
        analysis: SynchronizationOutcome,
    ) -> None:
        if analysis.forecast is None or analysis.stress_forecast is None:
            return
        if analysis.forecast == analysis.stress_forecast:
            return
        company = analysis.snapshot.company
        if company is None:
            return
        heading = QLabel("Стресс-сценарий")
        heading.setObjectName("sectionTitle")
        root_layout.addWidget(heading)
        card = QFrame()
        card.setObjectName("stressCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(24, 20, 24, 20)
        label = QLabel(
            "При моделировании дополнительной задержки минимальный остаток "
            f"изменяется с {format_money(analysis.forecast.minimum_balance, company.base_currency)} "
            f"до {format_money(analysis.stress_forecast.minimum_balance, company.base_currency)}."
        )
        label.setObjectName("readinessWarning")
        label.setWordWrap(True)
        layout.addWidget(label)
        root_layout.addWidget(card)

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow {
                background-color: #0b1020;
            }

            QScrollArea, QWidget#contentWidget {
                background-color: #0b1020;
            }

            QLabel#title {
                color: #f8fafc;
                font-size: 36px;
                font-weight: 700;
            }

            QLabel#subtitle {
                color: #94a3b8;
                font-size: 16px;
            }

            QLabel#demoNotice {
                color: #fde68a;
                background-color: #2b2412;
                border: 1px solid #80651c;
                border-radius: 10px;
                padding: 12px;
                font-size: 13px;
            }

            QPushButton#forecastButton {
                color: #07111f;
                background-color: #5eead4;
                border: none;
                border-radius: 10px;
                padding: 13px 22px;
                font-size: 16px;
                font-weight: 700;
            }

            QPushButton#forecastButton:hover {
                background-color: #99f6e4;
            }

            QPushButton#forecastButton:disabled {
                color: #64748b;
                background-color: #26324d;
            }

            QFrame#actionPanel {
                background-color: #11182a;
                border: 1px solid #26324d;
                border-radius: 12px;
            }

            QLabel#controlLabel {
                color: #cbd5e1;
                font-size: 14px;
            }

            QComboBox#scenarioSelector {
                color: #f8fafc;
                background-color: #151c2f;
                border: 1px solid #334155;
                border-radius: 8px;
                padding: 8px 12px;
                min-height: 22px;
            }

            QFrame#modePanel {
                background-color: transparent;
                border: none;
            }

            QPushButton#primaryForecastButton,
            QPushButton#stressForecastButton {
                color: #94a3b8;
                background-color: #151c2f;
                border: 1px solid #334155;
                border-radius: 8px;
                padding: 9px 14px;
            }

            QPushButton#primaryForecastButton:checked,
            QPushButton#stressForecastButton:checked {
                color: #f8fafc;
                background-color: #1d4ed8;
                border-color: #3b82f6;
            }

            QLabel#sectionTitle {
                color: #f8fafc;
                font-size: 20px;
                font-weight: 600;
            }

            QFrame#readinessReady {
                background-color: #102824;
                border: 1px solid #175e54;
                border-radius: 14px;
            }

            QFrame#readinessLimited {
                background-color: #2b2412;
                border: 1px solid #80651c;
                border-radius: 14px;
            }

            QFrame#readinessBlocked {
                background-color: #2a1522;
                border: 1px solid #7f1d3a;
                border-radius: 14px;
            }

            QLabel#readinessStatus {
                color: #f8fafc;
                font-size: 18px;
                font-weight: 600;
            }

            QLabel#readinessMeta {
                color: #94a3b8;
                font-size: 13px;
            }

            QLabel#readinessWarning {
                color: #fde68a;
                font-size: 14px;
            }

            QLabel#readinessError {
                color: #fda4af;
                font-size: 14px;
            }

            QFrame#metricCard {
                background-color: #151c2f;
                border: 1px solid #26324d;
                border-radius: 14px;
            }

            QLabel#metricCaption {
                color: #94a3b8;
                font-size: 13px;
            }

            QLabel#metricValue {
                color: #f8fafc;
                font-size: 21px;
                font-weight: 600;
            }

            QFrame#riskCard {
                background-color: #2a1522;
                border: 1px solid #7f1d3a;
                border-radius: 14px;
            }

            QFrame#safeCard {
                background-color: #102824;
                border: 1px solid #175e54;
                border-radius: 14px;
            }

            QFrame#emptyCard {
                background-color: #151c2f;
                border: 1px solid #26324d;
                border-radius: 14px;
            }

            QFrame#errorCard {
                background-color: #2a1522;
                border: 1px solid #7f1d3a;
                border-radius: 14px;
            }

            QFrame#detailsCard {
                background-color: #151c2f;
                border: 1px solid #26324d;
                border-radius: 14px;
            }

            QFrame#comparisonCard {
                background-color: #142033;
                border: 1px solid #2563eb;
                border-radius: 14px;
            }

            QFrame#stressCard {
                background-color: #2b2412;
                border: 1px solid #80651c;
                border-radius: 14px;
            }

            QLabel#detailText {
                color: #cbd5e1;
                font-size: 14px;
            }

            QLabel#comparisonTitle {
                color: #bfdbfe;
                font-size: 17px;
                font-weight: 600;
            }

            QLabel#statusTitle {
                color: #f8fafc;
                font-size: 19px;
                font-weight: 600;
            }

            QLabel#riskTitle {
                color: #f8fafc;
                font-size: 19px;
                font-weight: 600;
            }

            QLabel#description {
                color: #cbd5e1;
                font-size: 15px;
            }

            QLabel#auditNote {
                color: #64748b;
                font-size: 13px;
            }
            """
        )


def _dataset_label(dataset: DatasetKind) -> str:
    return {
        DatasetKind.COMPANY_PROFILE: "профиль компании",
        DatasetKind.ACCOUNT_BALANCES: "остатки",
        DatasetKind.ACCOUNTING_FACTS: "учётные факты",
        DatasetKind.PAYMENT_CALENDAR: "платёжный календарь",
        DatasetKind.BANK_TRANSACTIONS: "банковские операции",
    }[dataset]


def _localized_issue(code: str, message: str, impact: str) -> tuple[str, str]:
    if code in {
        "bank_coverage_stale",
        "bank_transactions_missing_in_accounting",
        "bank_reconciliation_ambiguous",
        "bank_reconciliation_conflict",
    }:
        return message, impact
    translations = {
        "company_profile_missing": (
            "Источник не передал профиль компании.",
            "Нельзя определить применимость фискальных правил и построить прогноз компании.",
        ),
        "account_balances_unavailable": (
            "Остатки по счетам недоступны.",
            "Невозможно определить начальную денежную позицию.",
        ),
        "account_balances_empty": (
            "Источник не вернул активных денежных счетов.",
            "Невозможно определить начальную денежную позицию.",
        ),
        "account_balance_stale": (
            "Остаток хотя бы одного счёта устарел.",
            "Прогноз начинается с потенциально неактуальной денежной позиции.",
        ),
        "account_currency_incompatible": (
            "Валюта хотя бы одного счёта отличается от базовой валюты компании.",
            "Для общего прогноза нужна явно заданная политика конвертации.",
        ),
        "payment_calendar_unavailable": (
            "Источник не передал платёжный календарь.",
            "В прогнозе могут отсутствовать будущие поступления и платежи.",
        ),
        "accounting_facts_unavailable": (
            "Источник не передал бухгалтерские показатели для фискального анализа.",
            "Часть фискальных обязательств может остаться нерассчитанной.",
        ),
        "event_currency_incompatible": (
            "Валюта хотя бы одного события отличается от базовой валюты компании.",
            "Событие нельзя учитывать без явно заданной политики конвертации.",
        ),
        "jurisdiction_missing": (
            "Не указана юрисдикция компании.",
            "Нельзя выбрать применимые фискальные правила.",
        ),
        "tax_regime_missing": (
            "Не указан налоговый режим компании.",
            "Нельзя надёжно рассчитать налоговые обязательства и льготы.",
        ),
        "one_c_company_mapping_failed": (
            "Карточка компании из 1С заполнена или сопоставлена не полностью.",
            "Нельзя надёжно определить компанию и применимые налоговые правила.",
        ),
        "one_c_balance_mapping_failed": (
            "Одна из записей об остатках из 1С не прошла проверку.",
            "Запись исключена; начальный остаток может быть неполным.",
        ),
        "one_c_metric_mapping_failed": (
            "Один из бухгалтерских показателей из 1С не прошёл проверку.",
            "Некоторые налоговые обязательства могут остаться нерассчитанными.",
        ),
        "one_c_accounting_event_mapping_failed": (
            "Одна из фактических операций 1С не прошла проверку.",
            "Фактические поступления или расходы могут быть отражены не полностью.",
        ),
        "one_c_payment_event_mapping_failed": (
            "Одна из записей платёжного календаря 1С не прошла проверку.",
            "Прогноз будущих поступлений и расходов может быть неполным.",
        ),
        "bank_transactions_unavailable": (
            "Банковские операции недоступны.",
            "Нельзя сверить последние поступления и расходы с бухгалтерией.",
        ),
        "bank_statements_empty": (
            "Банк не передал ни одной выписки.",
            "Нельзя подтвердить последние движения денежных средств.",
        ),
        "bank_coverage_stale": (
            "Банковская информация не охватывает последние дни.",
            "В прогнозе могут отсутствовать недавние поступления или расходы.",
        ),
        "bank_transactions_missing_in_accounting": (
            "В банке обнаружены операции, отсутствующие в бухгалтерских данных.",
            "Расходы или поступления могли быть не внесены бухгалтером.",
        ),
        "bank_reconciliation_ambiguous": (
            "Для некоторых банковских операций найдено несколько соответствий.",
            "FinRadar не выбирает неоднозначное соответствие автоматически.",
        ),
        "bank_reconciliation_conflict": (
            "Связанные банковские и бухгалтерские записи расходятся по значениям.",
            "Перед надёжным анализом необходимо исправить конфликтующие записи.",
        ),
        "bank_statement_balance_mismatch": (
            "Операции выписки не сходятся с её конечным остатком.",
            "Выписка может быть неполной или содержать неподдерживаемый тип операции.",
        ),
        "bank_accounting_balance_mismatch": (
            "Остаток банка отличается от остатка бухгалтерии на ту же дату.",
            "Начальная денежная позиция требует сверки.",
        ),
        "bank_duplicate_transaction": (
            "В банковской выписке обнаружена повторная операция.",
            "Повтор исключён из сверки.",
        ),
        "bank_transaction_id_derived": (
            "У банковской операции отсутствует стабильный идентификатор.",
            "FinRadar создал технический идентификатор; предпочтителен ID банка.",
        ),
        "bank_row_mapping_failed": (
            "Одна из строк банковской выписки не прошла проверку.",
            "Строка исключена; сверка с бухгалтерией может быть неполной.",
        ),
    }
    return translations.get(code, (message, impact))
