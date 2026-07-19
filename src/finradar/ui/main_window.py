from decimal import Decimal

from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QLabel,
    QMainWindow,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from finradar.application.synchronization_service import SynchronizationOutcome
from finradar.domain.data_readiness import IssueSeverity, ReadinessStatus
from finradar.domain.financial_snapshot import DatasetKind


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
        analysis: SynchronizationOutcome,
        horizon_days: int,
    ) -> None:
        super().__init__()

        self.setWindowTitle("FinRadar — Financial Early Warning")
        self.resize(1200, 760)
        self.setMinimumSize(960, 640)

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

        self._build_readiness_report(root_layout, analysis)

        if analysis.forecast is None or analysis.snapshot.company is None:
            self._build_empty_state(root_layout)
        else:
            self._build_dashboard(
                root_layout,
                analysis,
                horizon_days,
            )

        root_layout.addStretch()
        scroll_area.setWidget(content_widget)
        self.setCentralWidget(scroll_area)
        self._apply_styles()

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
                issue_label = QLabel(
                    f"{marker}: {message}\nВлияние: {impact}"
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
    }[dataset]


def _localized_issue(code: str, message: str, impact: str) -> tuple[str, str]:
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
    }
    return translations.get(code, (message, impact))
