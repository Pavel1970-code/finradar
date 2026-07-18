from decimal import Decimal

from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QLabel,
    QMainWindow,
    QVBoxLayout,
    QWidget,
)

from finradar.application.forecast_service import CompanyForecast


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
        dashboard: CompanyForecast | None,
    ) -> None:
        super().__init__()

        self.setWindowTitle("FinRadar — Financial Early Warning")
        self.resize(1200, 760)
        self.setMinimumSize(960, 640)

        central_widget = QWidget()
        root_layout = QVBoxLayout(central_widget)
        root_layout.setContentsMargins(42, 34, 42, 34)
        root_layout.setSpacing(24)

        title = QLabel("FinRadar")
        title.setObjectName("title")
        root_layout.addWidget(title)

        if dashboard is None:
            self._build_empty_state(root_layout)
        else:
            self._build_dashboard(
                root_layout,
                dashboard,
            )

        root_layout.addStretch()
        self.setCentralWidget(central_widget)
        self._apply_styles()

    def _build_empty_state(
        self,
        root_layout: QVBoxLayout,
    ) -> None:
        subtitle = QLabel(
            "В базе данных пока нет компании."
        )
        subtitle.setObjectName("subtitle")

        empty_card = QFrame()
        empty_card.setObjectName("emptyCard")

        card_layout = QVBoxLayout(empty_card)
        card_layout.setContentsMargins(26, 24, 26, 24)

        message = QLabel(
            "Добавьте компанию и финансовые операции "
            "или запустите генератор демонстрационных данных."
        )
        message.setObjectName("description")
        message.setWordWrap(True)

        card_layout.addWidget(message)

        root_layout.addWidget(subtitle)
        root_layout.addWidget(empty_card)

    def _build_dashboard(
        self,
        root_layout: QVBoxLayout,
        dashboard: CompanyForecast,
    ) -> None:
        result = dashboard.result

        subtitle = QLabel(
            f"{dashboard.company_name} · "
            f"Прогноз на 30 дней · "
            f"Операций: {dashboard.event_count}"
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
                    dashboard.currency,
                ),
            ),
            create_metric_card(
                "Остаток через 30 дней",
                format_money(
                    result.closing_balance,
                    dashboard.currency,
                ),
            ),
            create_metric_card(
                "Минимальный баланс",
                format_money(
                    result.minimum_balance,
                    dashboard.currency,
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
                f"{format_money(result.required_funding, dashboard.currency)}."
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

            QLabel#title {
                color: #f8fafc;
                font-size: 36px;
                font-weight: 700;
            }

            QLabel#subtitle {
                color: #94a3b8;
                font-size: 16px;
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