from collections.abc import Callable
from decimal import Decimal
from enum import Enum

from PySide6.QtCore import QThread, Signal

from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from finradar.application.synchronization_service import SynchronizationOutcome
from finradar.domain.data_readiness import IssueSeverity, ReadinessStatus
from finradar.domain.financial_snapshot import DatasetKind


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
        forecast_runner: Callable[[], SynchronizationOutcome] | None = None,
        demo_notice: str | None = None,
    ) -> None:
        super().__init__()

        self._analysis = analysis
        self._horizon_days = horizon_days
        self._forecast_runner = forecast_runner
        self._demo_notice = demo_notice
        self._error_message: str | None = None
        self._worker: _ForecastWorker | None = None
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

        worker = _ForecastWorker(self._forecast_runner)
        self._worker = worker
        worker.result_ready.connect(self._accept_result)
        worker.failed.connect(self._accept_error)
        worker.finished.connect(self._release_worker)
        worker.start()

    def _accept_result(self, analysis: SynchronizationOutcome) -> None:
        self._analysis = analysis
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
            self._build_readiness_report(root_layout, self._analysis)
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

        root_layout.addStretch()
        scroll_area.setWidget(content_widget)
        self.setCentralWidget(scroll_area)

    def _build_action_panel(self, root_layout: QVBoxLayout) -> None:
        if self._forecast_runner is None:
            return
        button = QPushButton(
            "Обновить прогноз"
            if self._analysis is not None
            else "Дать прогноз"
        )
        button.setObjectName("forecastButton")
        button.setEnabled(self._state is not ForecastUiState.RUNNING)
        button.clicked.connect(self.start_forecast)
        root_layout.addWidget(button)

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

        supplied = ", ".join(
            _dataset_label(dataset)
            for dataset in DatasetKind
            if analysis.snapshot.supplies(dataset)
        )
        source_label = QLabel(
            f"Источник: {analysis.snapshot.source_system} · Получено: {supplied or 'нет данных'}"
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
            for issue in report.issues:
                marker = "Ошибка" if issue.severity is IssueSeverity.ERROR else "Ограничение"
                message, impact = _localized_issue(issue.code, issue.message, issue.impact)
                source_reference = (
                    f"\nЗапись источника: {issue.source_reference}"
                    if issue.source_reference
                    else ""
                )
                issue_label = QLabel(
                    f"{marker}: {message}\nВлияние: {impact}{source_reference}"
                )
                issue_label.setObjectName(
                    "readinessError"
                    if issue.severity is IssueSeverity.ERROR
                    else "readinessWarning"
                )
                issue_label.setWordWrap(True)
                card_layout.addWidget(issue_label)

        root_layout.addWidget(card)

    def _build_dashboard(
        self,
        root_layout: QVBoxLayout,
        analysis: SynchronizationOutcome,
        horizon_days: int,
    ) -> None:
        result = analysis.forecast
        company = analysis.snapshot.company
        assert result is not None
        assert company is not None

        subtitle = QLabel(
            f"{company.name} · "
            f"Прогноз на {horizon_days} дней · "
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
