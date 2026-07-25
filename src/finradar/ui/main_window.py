from collections.abc import Callable
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum

from PySide6.QtCore import QPointF, QRectF, Qt, QThread, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath, QPen

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
from finradar.application.forecast_history import (
    ForecastHistoryDetails,
    ForecastHistoryItem,
)
from finradar.domain.data_readiness import ReadinessStatus
from finradar.domain.financial_snapshot import (
    CounterpartyKind,
    DatasetKind,
    FinancialDirection,
    FinancialEvent,
    FinancialEventKind,
    FinancialEventStatus,
)
from finradar.domain.forecast import ForecastResult
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


class BalanceChart(QWidget):
    """Small dependency-free balance chart for the desktop forecast."""

    def __init__(self, result: ForecastResult, currency: str) -> None:
        super().__init__()
        self._result = result
        self._currency = currency
        self.setObjectName("balanceChart")
        self.setMinimumHeight(250)
        self.setProperty("pointCount", len(result.points))
        self.setProperty("minimumBalance", str(result.minimum_balance))

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API name
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#151c2f"))
        if not self._result.points:
            return

        margins = (74.0, 24.0, 24.0, 42.0)
        plot = QRectF(
            margins[0],
            margins[1],
            max(1.0, self.width() - margins[0] - margins[2]),
            max(1.0, self.height() - margins[1] - margins[3]),
        )
        balances = [self._result.opening_balance]
        balances.extend(point.closing_balance for point in self._result.points)
        low = min(balances + [Decimal("0.00")])
        high = max(balances + [Decimal("0.00")])
        if low == high:
            high += Decimal("1.00")
        padding = max((high - low) * Decimal("0.08"), Decimal("1.00"))
        low -= padding
        high += padding

        def y_position(value: Decimal) -> float:
            ratio = float((high - value) / (high - low))
            return plot.top() + ratio * plot.height()

        painter.setPen(QPen(QColor("#334155"), 1))
        for index in range(5):
            y = plot.top() + plot.height() * index / 4
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            value = high - (high - low) * Decimal(index) / Decimal(4)
            visible_value = (
                Decimal("0.00")
                if abs(value) < (high - low) * Decimal("0.01")
                else value
            )
            label = f"{visible_value:,.0f}"
            painter.setPen(QColor("#94a3b8"))
            painter.drawText(
                QRectF(4, y - 9, margins[0] - 12, 18),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                label,
            )
            painter.setPen(QPen(QColor("#334155"), 1))

        if low < Decimal("0.00") < high:
            zero_y = y_position(Decimal("0.00"))
            painter.setPen(QPen(QColor("#fb7185"), 1, Qt.PenStyle.DashLine))
            painter.drawLine(
                QPointF(plot.left(), zero_y), QPointF(plot.right(), zero_y)
            )

        points = self._result.points
        path = QPainterPath()
        for index, point in enumerate(points):
            x = (
                plot.left()
                if len(points) == 1
                else plot.left() + plot.width() * index / (len(points) - 1)
            )
            chart_point = QPointF(x, y_position(point.closing_balance))
            if index == 0:
                path.moveTo(chart_point)
            else:
                path.lineTo(chart_point)
        painter.setPen(QPen(QColor("#5eead4"), 3))
        painter.drawPath(path)

        painter.setPen(QColor("#94a3b8"))
        font_metrics = QFontMetrics(painter.font())
        labels = ((0, points[0].day), (len(points) - 1, points[-1].day))
        for index, day in labels:
            x = (
                plot.left()
                if len(points) == 1
                else plot.left() + plot.width() * index / (len(points) - 1)
            )
            label = day.strftime("%d.%m")
            width = font_metrics.horizontalAdvance(label)
            painter.drawText(QPointF(x - width / 2, plot.bottom() + 25), label)

        painter.drawText(
            QRectF(plot.left(), 2, plot.width(), 18),
            Qt.AlignmentFlag.AlignRight,
            self._currency,
        )


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
        demo_notices: dict[str, str] | None = None,
        calculated_at: datetime | None = None,
        history_provider: Callable[[], tuple[ForecastHistoryItem, ...]] | None = None,
        history_loader: Callable[[str], ForecastHistoryDetails] | None = None,
    ) -> None:
        super().__init__()

        self._analysis = analysis
        self._horizon_days = horizon_days
        self._forecast_runner = forecast_runner
        self._demo_scenarios = demo_scenarios
        self._selected_scenario_id = initial_scenario_id
        if self._selected_scenario_id is None and demo_scenarios:
            self._selected_scenario_id = demo_scenarios[0][0]
        self._demo_notices = dict(demo_notices or {})
        self._demo_notice = self._demo_notices.get(
            self._selected_scenario_id,
            demo_notice,
        )
        self._calculated_at = calculated_at
        self._history_provider = history_provider
        self._history_loader = history_loader
        self._history_items: tuple[ForecastHistoryItem, ...] = ()
        self._history_details: ForecastHistoryDetails | None = None
        self._history_error: str | None = None
        self._error_message: str | None = None
        self._worker: _ForecastWorker | None = None
        self._show_stress = False
        self._state = (
            ForecastUiState.RESULT if analysis is not None else ForecastUiState.IDLE
        )
        self._refresh_history()

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
        self._calculated_at = datetime.now().astimezone()
        self._history_details = None
        self._show_stress = False
        self._state = ForecastUiState.RESULT
        self._error_message = None
        self._refresh_history()
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

        if self._history_details is not None:
            self._build_history_details(root_layout, self._history_details)
        elif self._state is ForecastUiState.IDLE:
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

        self._build_history(root_layout)

        root_layout.addStretch()
        scroll_area.setWidget(content_widget)
        self.setCentralWidget(scroll_area)

    def _refresh_history(self) -> None:
        if self._history_provider is None:
            return
        try:
            self._history_items = self._history_provider()
            self._history_error = None
        except Exception:  # Local history failure must not prevent a new forecast.
            self._history_items = ()
            self._history_error = "Не удалось прочитать локальную историю прогнозов."

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
        self._demo_notice = self._demo_notices.get(scenario_id, self._demo_notice)
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

        if self._calculated_at is not None:
            calculated_label = QLabel(
                "Последний успешный расчёт: "
                f"{self._calculated_at.astimezone().strftime('%d.%m.%Y %H:%M')}"
            )
            calculated_label.setObjectName("lastCalculated")
            root_layout.addWidget(calculated_label)

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

        self._build_balance_chart(root_layout, result, company.base_currency)
        self._build_payment_calendar(root_layout, analysis, result)

        audit_note = QLabel(
            "Расчёт выполнен детерминированным ядром. "
            "AI не участвует в вычислении финансовых показателей."
        )
        audit_note.setObjectName("auditNote")
        audit_note.setWordWrap(True)

        root_layout.addWidget(audit_note)

    def _build_balance_chart(
        self,
        root_layout: QVBoxLayout,
        result: ForecastResult,
        currency: str,
    ) -> None:
        heading = QLabel("Динамика остатка")
        heading.setObjectName("sectionTitle")
        root_layout.addWidget(heading)

        card = QFrame()
        card.setObjectName("chartCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 12, 12, 8)
        chart = BalanceChart(result, currency)
        layout.addWidget(chart)
        root_layout.addWidget(card)

    def _build_payment_calendar(
        self,
        root_layout: QVBoxLayout,
        analysis: SynchronizationOutcome,
        result: ForecastResult,
    ) -> None:
        events = tuple(
            event
            for event in analysis.snapshot.events
            if event.kind is FinancialEventKind.PLANNED
            and event.status is not FinancialEventStatus.CANCELLED
            and event.amount > event.settled_amount
            and event.due_date <= result.end_date
        )
        tax_events = tuple(event for event in events if _is_tax_event(event))
        receivables = tuple(
            event
            for event in events
            if event.direction is FinancialDirection.INFLOW
            and not _is_tax_event(event)
        )
        payables = tuple(
            event
            for event in events
            if event.direction is FinancialDirection.OUTFLOW
            and not _is_tax_event(event)
        )
        self._build_event_calendar_section(
            root_layout,
            title="Ожидаемые поступления",
            empty_text="В платёжном календаре нет ожидаемых поступлений.",
            events=receivables,
            as_of=result.start_date,
            row_object_name="receivableRow",
            amount_object_name="receiptAmount",
        )
        self._build_event_calendar_section(
            root_layout,
            title="Предстоящие выплаты",
            empty_text="В платёжном календаре нет предстоящих выплат.",
            events=payables,
            as_of=result.start_date,
            row_object_name="payableRow",
            amount_object_name="paymentAmount",
        )
        self._build_tax_calendar(
            root_layout,
            analysis=analysis,
            tax_events=tax_events,
            as_of=result.start_date,
        )

    def _build_event_calendar_section(
        self,
        root_layout: QVBoxLayout,
        *,
        title: str,
        empty_text: str,
        events: tuple[FinancialEvent, ...],
        as_of,
        row_object_name: str,
        amount_object_name: str,
    ) -> None:
        heading = QLabel(title)
        heading.setObjectName("sectionTitle")
        root_layout.addWidget(heading)
        card = QFrame()
        card.setObjectName("paymentsCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(24, 12, 24, 12)
        layout.setSpacing(0)
        if not events:
            empty = QLabel(empty_text)
            empty.setObjectName("historyEmpty")
            layout.addWidget(empty)
        else:
            ordered = tuple(
                sorted(events, key=lambda item: (item.due_date, -item.amount))
            )[:8]
            for index, event in enumerate(ordered):
                self._add_event_calendar_row(
                    layout,
                    event,
                    as_of=as_of,
                    row_object_name=row_object_name,
                    amount_object_name=amount_object_name,
                )
                if index != len(ordered) - 1:
                    _add_separator(layout, "paymentSeparator")
        root_layout.addWidget(card)

    def _add_event_calendar_row(
        self,
        layout: QVBoxLayout,
        event: FinancialEvent,
        *,
        as_of,
        row_object_name: str,
        amount_object_name: str,
    ) -> None:
        row = QFrame()
        row.setObjectName(row_object_name)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 12, 0, 12)
        row_layout.setSpacing(16)

        date_label = QLabel(event.due_date.strftime("%d.%m.%Y"))
        date_label.setObjectName(
            "overdueDate" if event.due_date < as_of else "paymentDate"
        )
        date_label.setMinimumWidth(92)
        row_layout.addWidget(date_label)

        details_layout = QVBoxLayout()
        details_layout.setSpacing(4)
        title = QLabel(event.title)
        title.setObjectName("paymentTitle")
        title.setWordWrap(True)
        details_layout.addWidget(title)
        counterparty = (
            event.counterparty.name
            if event.counterparty is not None
            else "Контрагент не указан"
        )
        purpose = event.payment_purpose or "Назначение платежа не указано"
        party_label = QLabel(f"{counterparty} · {purpose}")
        party_label.setObjectName("paymentDetails")
        party_label.setWordWrap(True)
        details_layout.addWidget(party_label)
        basis = QLabel(_event_basis_text(event))
        basis.setObjectName("paymentBasis")
        basis.setWordWrap(True)
        details_layout.addWidget(basis)
        row_layout.addLayout(details_layout, 1)

        amount_layout = QVBoxLayout()
        amount_layout.setSpacing(4)
        outstanding = max(event.amount - event.settled_amount, Decimal("0.00"))
        amount = QLabel(format_money(outstanding, event.currency))
        amount.setObjectName(amount_object_name)
        status = QLabel(_event_status_text(event, as_of=as_of))
        status.setObjectName(
            "overdueStatus" if event.due_date < as_of else "paymentStatus"
        )
        amount_layout.addWidget(amount)
        amount_layout.addWidget(status)
        row_layout.addLayout(amount_layout)
        layout.addWidget(row)

    def _build_tax_calendar(
        self,
        root_layout: QVBoxLayout,
        *,
        analysis: SynchronizationOutcome,
        tax_events: tuple[FinancialEvent, ...],
        as_of,
    ) -> None:
        recorded_obligation_keys = {
            event.obligation_key
            for event in tax_events
            if event.obligation_key is not None
        }
        obligations = tuple(
            (item.calculation.obligation, item.reconciliation)
            for item in analysis.rule_analyses
            if item.calculation.obligation is not None
            and item.reconciliation is not None
            and item.reconciliation.outstanding_amount > Decimal("0.00")
            and item.calculation.obligation.obligation_key
            not in recorded_obligation_keys
        )
        if not tax_events and not obligations:
            return
        heading = QLabel("Налоговый календарь")
        heading.setObjectName("sectionTitle")
        root_layout.addWidget(heading)
        card = QFrame()
        card.setObjectName("taxCalendarCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(24, 12, 24, 12)
        layout.setSpacing(0)

        rows: list[tuple[object, str]] = [
            (event, "event") for event in tax_events
        ]
        rows.extend((item, "obligation") for item in obligations)
        rows.sort(
            key=lambda row: (
                row[0].due_date
                if row[1] == "event"
                else row[0][0].due_date
            )
        )
        for index, (value, kind) in enumerate(rows):
            if kind == "event":
                self._add_event_calendar_row(
                    layout,
                    value,
                    as_of=as_of,
                    row_object_name="taxCalendarRow",
                    amount_object_name="taxCalendarAmount",
                )
            else:
                obligation, reconciliation = value
                self._add_tax_obligation_row(
                    layout,
                    obligation=obligation,
                    outstanding_amount=reconciliation.outstanding_amount,
                    as_of=as_of,
                )
            if index != len(rows) - 1:
                _add_separator(layout, "paymentSeparator")
        root_layout.addWidget(card)

    def _add_tax_obligation_row(
        self,
        layout: QVBoxLayout,
        *,
        obligation,
        outstanding_amount: Decimal,
        as_of,
    ) -> None:
        row = QFrame()
        row.setObjectName("taxCalendarRow")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 12, 0, 12)
        row_layout.setSpacing(16)
        due_date = QLabel(obligation.due_date.strftime("%d.%m.%Y"))
        due_date.setObjectName(
            "overdueDate" if obligation.due_date < as_of else "paymentDate"
        )
        due_date.setMinimumWidth(92)
        row_layout.addWidget(due_date)

        details_layout = QVBoxLayout()
        details_layout.setSpacing(4)
        title = QLabel(obligation.title)
        title.setObjectName("paymentTitle")
        details_layout.addWidget(title)
        recipient = (
            obligation.payment_recipient.name
            if obligation.payment_recipient is not None
            else "Налоговый орган"
        )
        recipient_label = QLabel(f"{recipient} · детерминированный расчёт")
        recipient_label.setObjectName("paymentDetails")
        details_layout.addWidget(recipient_label)
        period = QLabel(
            _period_text(obligation.period_start, obligation.period_end)
        )
        period.setObjectName("paymentBasis")
        details_layout.addWidget(period)
        row_layout.addLayout(details_layout, 1)

        amount_layout = QVBoxLayout()
        amount_layout.setSpacing(4)
        amount = QLabel(format_money(outstanding_amount, obligation.currency))
        amount.setObjectName("taxCalendarAmount")
        status = QLabel(
            "Просрочено"
            if obligation.due_date < as_of
            else "Рассчитано, ожидает оплаты"
        )
        status.setObjectName(
            "overdueStatus" if obligation.due_date < as_of else "paymentStatus"
        )
        amount_layout.addWidget(amount)
        amount_layout.addWidget(status)
        row_layout.addLayout(amount_layout)
        layout.addWidget(row)

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
        if (
            not view_model.fiscal_calculations
            and not view_model.obligations
            and not view_model.consequences
        ):
            return

        heading = QLabel("Налоги и возможные последствия")
        heading.setObjectName("sectionTitle")
        root_layout.addWidget(heading)
        card = QFrame()
        card.setObjectName("detailsCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        for calculation in view_model.fiscal_calculations:
            if not calculation.resolved:
                fields = ", ".join(calculation.missing_fields) or "исходные данные"
                label = QLabel(
                    f"{calculation.title}\n"
                    "Расчёт не выполнен и не включён в прогноз. "
                    f"Не хватает или требуется уточнить: {fields}."
                )
                label.setObjectName("readinessWarning")
                label.setWordWrap(True)
                layout.addWidget(label)
                continue
            if len(calculation.components) <= 1:
                continue
            assert calculation.net_amount is not None
            component_lines = "\n".join(
                f"• {component.title}: "
                f"{format_money(component.amount, component.currency)}"
                for component in calculation.components
            )
            label = QLabel(
                f"{calculation.title}: {calculation.position_text}\n"
                f"{component_lines}\n"
                "Итоговая налоговая позиция: "
                f"{format_money(calculation.net_amount, calculation.currency)}.\n"
                f"{_fiscal_source_text(calculation.source_reference)}"
            )
            label.setObjectName("detailText")
            label.setWordWrap(True)
            layout.addWidget(label)

        for obligation in view_model.obligations:
            rate = (obligation.rate * Decimal("100")).normalize()
            period_text = _period_text(
                obligation.period_start,
                obligation.period_end,
            )
            label = QLabel(
                f"{obligation.title}\n"
                f"Расчёт: {rate}% от базы — "
                f"{format_money(obligation.amount, obligation.currency)}. "
                f"Срок: {obligation.due_date.strftime('%d.%m.%Y')}. "
                "Осталось оплатить: "
                f"{format_money(obligation.outstanding_amount, obligation.currency)}.\n"
                f"Получатель: {obligation.recipient_name}. {period_text}."
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
            "Это расчёт прототипа на данных выбранного сценария. "
            "Перед использованием с реальной компанией необходимы проверка "
            "налогового статуса, полноты операций и актуальности нормативной базы. "
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

    def _build_history(self, root_layout: QVBoxLayout) -> None:
        if self._history_provider is None:
            return
        heading = QLabel("Последние прогнозы")
        heading.setObjectName("sectionTitle")
        root_layout.addWidget(heading)
        if self._history_error is not None:
            error = QLabel(self._history_error)
            error.setObjectName("readinessError")
            root_layout.addWidget(error)
            return
        if not self._history_items:
            empty = QLabel(
                "История пока пуста. После первого расчёта прогноз появится здесь."
            )
            empty.setObjectName("historyEmpty")
            empty.setWordWrap(True)
            root_layout.addWidget(empty)
            return

        card = QFrame()
        card.setObjectName("historyPanel")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 10, 20, 10)
        layout.setSpacing(0)
        scenario_titles = dict(self._demo_scenarios)
        for index, item in enumerate(self._history_items):
            row = QFrame()
            row.setObjectName("historyRow")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 12, 0, 12)
            row_layout.setSpacing(16)

            title = scenario_titles.get(item.scenario_id, item.company_name)
            version = (
                f" · версия {item.scenario_version}"
                if item.scenario_version is not None
                else ""
            )
            identity = QLabel(
                f"{title}{version}\n"
                f"Расчёт: {_format_local_datetime(item.created_at)}"
            )
            identity.setObjectName("historyIdentity")
            identity.setWordWrap(True)
            row_layout.addWidget(identity, 2)

            if item.available:
                gap = (
                    item.first_gap_date.strftime("%d.%m.%Y")
                    if item.first_gap_date is not None
                    else "не обнаружен"
                )
                assert item.required_funding is not None
                readiness = {
                    "ready": "данные полные",
                    "limited": "есть ограничения",
                    "blocked": "анализ заблокирован",
                }.get(item.readiness_status, "статус неизвестен")
                summary = QLabel(
                    f"Данные: {readiness} · разрыв: {gap}\n"
                    "Финансирование: "
                    f"{format_money(item.required_funding, item.currency)}"
                )
                summary.setObjectName("historySummary")
                row_layout.addWidget(summary, 2)
                button = QPushButton("Открыть")
                button.setObjectName("historyOpenButton")
                button.setProperty("analysisRunId", item.analysis_run_id)
                button.clicked.connect(
                    lambda checked=False, run_id=item.analysis_run_id: (
                        self._open_history(run_id)
                    )
                )
                row_layout.addWidget(button)
            else:
                unavailable = QLabel(item.error_message or "Запись недоступна.")
                unavailable.setObjectName("readinessError")
                unavailable.setWordWrap(True)
                row_layout.addWidget(unavailable, 2)
            layout.addWidget(row)
            if index != len(self._history_items) - 1:
                separator = QFrame()
                separator.setObjectName("historySeparator")
                separator.setFrameShape(QFrame.Shape.HLine)
                layout.addWidget(separator)
        root_layout.addWidget(card)

    def _open_history(self, analysis_run_id: str) -> None:
        if self._history_loader is None:
            return
        try:
            self._history_details = self._history_loader(analysis_run_id)
            self._history_error = None
            self._show_stress = False
        except (LookupError, ValueError):
            self._history_details = None
            self._history_error = (
                "Сохранённый прогноз недоступен: проверка целостности не пройдена."
            )
        self._render()

    def _close_history_details(self) -> None:
        self._history_details = None
        self._show_stress = False
        self._render()

    def _build_history_details(
        self,
        root_layout: QVBoxLayout,
        details: ForecastHistoryDetails,
    ) -> None:
        header = QFrame()
        header.setObjectName("historyDetailHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(18, 14, 18, 14)
        title = QLabel("Сохранённый прогноз")
        title.setObjectName("statusTitle")
        header_layout.addWidget(title)
        header_layout.addStretch()
        close = QPushButton("Вернуться к текущему прогнозу")
        close.setObjectName("historyCloseButton")
        close.clicked.connect(self._close_history_details)
        header_layout.addWidget(close)
        root_layout.addWidget(header)

        item = details.item
        meta = QLabel(
            f"{item.company_name} · дата анализа "
            f"{item.analysis_date.strftime('%d.%m.%Y')} · "
            f"сохранено {_format_local_datetime(item.created_at)}"
        )
        meta.setObjectName("subtitle")
        meta.setWordWrap(True)
        root_layout.addWidget(meta)

        result = details.forecast
        metrics = QGridLayout()
        cards = (
            create_metric_card(
                "Начальный остаток",
                format_money(result.opening_balance, item.currency),
            ),
            create_metric_card(
                "Остаток на конец периода",
                format_money(result.closing_balance, item.currency),
            ),
            create_metric_card(
                "Минимальный баланс",
                format_money(result.minimum_balance, item.currency),
                state="danger" if result.minimum_balance < 0 else "safe",
            ),
            create_metric_card(
                "Первый кассовый разрыв",
                (
                    result.first_gap_date.strftime("%d.%m.%Y")
                    if result.first_gap_date is not None
                    else "Не обнаружен"
                ),
                state="danger" if result.first_gap_date is not None else "safe",
            ),
        )
        for column, card in enumerate(cards):
            metrics.addWidget(card, 0, column)
            metrics.setColumnStretch(column, 1)
        root_layout.addLayout(metrics)

        self._build_balance_chart(root_layout, result, item.currency)
        self._build_historical_payments(root_layout, details)
        self._build_historical_fiscal_summary(root_layout, details)

        note = QLabel(
            "Показаны сохранённые результаты и сохранённый набор прогнозных "
            "событий. Финансовый расчёт повторно не выполнялся."
        )
        note.setObjectName("auditNote")
        note.setWordWrap(True)
        root_layout.addWidget(note)

    def _build_historical_payments(
        self,
        root_layout: QVBoxLayout,
        details: ForecastHistoryDetails,
    ) -> None:
        events = tuple(
            event
            for event in details.payment_events
            if event.status is not FinancialEventStatus.CANCELLED
            and event.amount > event.settled_amount
            and event.due_date <= details.forecast.end_date
        )
        receivables = tuple(
            event
            for event in events
            if event.direction is FinancialDirection.INFLOW
            and not _is_tax_event(event)
        )
        payables = tuple(
            event
            for event in events
            if event.direction is FinancialDirection.OUTFLOW
            and not _is_tax_event(event)
        )
        tax_events = tuple(event for event in events if _is_tax_event(event))
        self._build_event_calendar_section(
            root_layout,
            title="Сохранённые ожидаемые поступления",
            empty_text="Ожидаемых поступлений в сохранённом прогнозе нет.",
            events=receivables,
            as_of=details.forecast.start_date,
            row_object_name="receivableRow",
            amount_object_name="receiptAmount",
        )
        self._build_event_calendar_section(
            root_layout,
            title="Сохранённые предстоящие выплаты",
            empty_text="Предстоящих выплат в сохранённом прогнозе нет.",
            events=payables,
            as_of=details.forecast.start_date,
            row_object_name="payableRow",
            amount_object_name="paymentAmount",
        )
        if tax_events:
            self._build_event_calendar_section(
                root_layout,
                title="Сохранённый налоговый календарь",
                empty_text="",
                events=tax_events,
                as_of=details.forecast.start_date,
                row_object_name="taxCalendarRow",
                amount_object_name="taxCalendarAmount",
            )

    def _build_historical_fiscal_summary(
        self,
        root_layout: QVBoxLayout,
        details: ForecastHistoryDetails,
    ) -> None:
        if not details.obligations and not details.consequences:
            return
        heading = QLabel("Сохранённые налоги и последствия")
        heading.setObjectName("sectionTitle")
        root_layout.addWidget(heading)
        card = QFrame()
        card.setObjectName("detailsCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(24, 18, 24, 18)
        for obligation in details.obligations:
            period = _period_text(
                obligation.period_start,
                obligation.period_end,
            )
            label = QLabel(
                f"{obligation.title}: "
                f"{format_money(obligation.amount, obligation.currency)}; "
                f"осталось {format_money(obligation.outstanding_amount, obligation.currency)}; "
                f"срок {obligation.due_date.strftime('%d.%m.%Y')}; "
                f"получатель: {obligation.recipient_name}; {period}."
            )
            label.setObjectName("detailText")
            label.setWordWrap(True)
            layout.addWidget(label)
        for consequence in details.consequences:
            title = {
                "late_payment_penalty": "Пеня",
                "fine": "Штраф",
            }.get(consequence.consequence_type, "Фискальное последствие")
            amount = (
                format_money(consequence.amount, consequence.currency)
                if consequence.amount is not None
                else "сумма не определена"
            )
            label = QLabel(
                f"{title}: {amount}; дата оценки "
                f"{consequence.assessment_date.strftime('%d.%m.%Y')}."
            )
            label.setObjectName("detailText")
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

            QLabel#lastCalculated {
                color: #64748b;
                font-size: 13px;
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

            QFrame#chartCard,
            QFrame#paymentsCard,
            QFrame#taxCalendarCard,
            QFrame#historyPanel,
            QFrame#historyDetailHeader {
                background-color: #151c2f;
                border: 1px solid #26324d;
                border-radius: 14px;
            }

            QLabel#paymentTitle {
                color: #e2e8f0;
                font-size: 14px;
                font-weight: 600;
            }

            QLabel#paymentDate,
            QLabel#paymentDetails,
            QLabel#paymentBasis,
            QLabel#paymentStatus {
                color: #94a3b8;
                font-size: 13px;
            }

            QLabel#paymentDate {
                min-width: 90px;
            }

            QLabel#paymentAmount,
            QLabel#receiptAmount,
            QLabel#taxCalendarAmount {
                color: #f8fafc;
                font-size: 14px;
                font-weight: 600;
                min-width: 120px;
            }

            QLabel#receiptAmount {
                color: #5eead4;
            }

            QLabel#taxCalendarAmount {
                color: #fde68a;
            }

            QLabel#overdueDate,
            QLabel#overdueStatus {
                color: #fb7185;
                font-size: 13px;
                font-weight: 600;
            }

            QFrame#paymentSeparator {
                color: #26324d;
                max-height: 1px;
            }

            QLabel#historyIdentity {
                color: #e2e8f0;
                font-size: 14px;
            }

            QLabel#historySummary,
            QLabel#historyEmpty {
                color: #94a3b8;
                font-size: 13px;
            }

            QPushButton#historyOpenButton,
            QPushButton#historyCloseButton {
                color: #dbeafe;
                background-color: #142033;
                border: 1px solid #2563eb;
                border-radius: 8px;
                padding: 8px 13px;
            }

            QPushButton#historyOpenButton:hover,
            QPushButton#historyCloseButton:hover {
                background-color: #1e3a5f;
            }

            QFrame#historySeparator {
                color: #26324d;
                max-height: 1px;
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


def _is_tax_event(event: FinancialEvent) -> bool:
    return (
        event.counterparty is not None
        and event.counterparty.kind is CounterpartyKind.TAX_AUTHORITY
    ) or (event.category or "").startswith("tax")


def _event_basis_text(event: FinancialEvent) -> str:
    parts: list[str] = []
    if event.payment_basis is not None:
        document_types = {
            "invoice": "Счёт",
            "delivery_note": "Накладная",
            "contract": "Договор",
            "payroll_register": "Расчётная ведомость",
            "tax_notice": "Налоговое обязательство",
        }
        document_type = document_types.get(
            event.payment_basis.document_type,
            event.payment_basis.document_type,
        )
        parts.append(
            f"{document_type} №{event.payment_basis.document_number} "
            f"от {event.payment_basis.document_date.strftime('%d.%m.%Y')}"
        )
        if event.payment_basis.description:
            parts.append(event.payment_basis.description)
    else:
        parts.append("Документ-основание не указан")
    if event.period_start is not None or event.period_end is not None:
        parts.append(_period_text(event.period_start, event.period_end))
    return " · ".join(parts)


def _period_text(period_start: date | None, period_end: date | None) -> str:
    if period_start is None and period_end is None:
        return "Период не указан"
    if period_start is None or period_end is None:
        return "Период указан не полностью"
    return (
        f"Период: {period_start.strftime('%d.%m.%Y')}–"
        f"{period_end.strftime('%d.%m.%Y')}"
    )


def _fiscal_source_text(source_reference: str) -> str:
    if "matsne.gov.ge" in source_reference:
        return (
            "Нормативная основа: Налоговый кодекс Грузии, "
            "статьи 166–168 и 181."
        )
    return "Нормативная основа: правило выбранного демонстрационного сценария."


def _event_status_text(event: FinancialEvent, *, as_of: date) -> str:
    if (
        event.status is FinancialEventStatus.SETTLED
        or event.settled_amount >= event.amount
    ):
        return "Оплачено"
    if event.settled_amount > Decimal("0.00"):
        return (
            "Частично оплачено: "
            f"{format_money(event.settled_amount, event.currency)}"
        )
    if event.due_date < as_of:
        return "Просрочено"
    if event.status is FinancialEventStatus.CONFIRMED:
        return "Подтверждено"
    return "Запланировано"


def _add_separator(layout: QVBoxLayout, object_name: str) -> None:
    separator = QFrame()
    separator.setObjectName(object_name)
    separator.setFrameShape(QFrame.Shape.HLine)
    layout.addWidget(separator)


def _format_local_datetime(value: datetime) -> str:
    aware = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return aware.astimezone().strftime("%d.%m.%Y %H:%M")


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
