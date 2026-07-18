from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QMainWindow,
    QVBoxLayout,
    QWidget,
)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()

        self.setWindowTitle("FinRadar — Financial Early Warning")
        self.resize(1200, 760)
        self.setMinimumSize(900, 600)

        central_widget = QWidget()
        root_layout = QVBoxLayout(central_widget)
        root_layout.setContentsMargins(48, 40, 48, 40)
        root_layout.setSpacing(24)

        title = QLabel("FinRadar")
        title.setObjectName("title")

        subtitle = QLabel(
            "Система раннего предупреждения финансовых рисков малого бизнеса"
        )
        subtitle.setObjectName("subtitle")
        subtitle.setWordWrap(True)

        status_card = QFrame()
        status_card.setObjectName("statusCard")

        card_layout = QVBoxLayout(status_card)
        card_layout.setContentsMargins(28, 24, 28, 24)
        card_layout.setSpacing(10)

        status_label = QLabel("Прототип запущен")
        status_label.setObjectName("statusLabel")

        description = QLabel(
            "Следующий этап: локальная база данных и детерминированный "
            "расчёт прогноза денежных средств на 30 дней."
        )
        description.setObjectName("description")
        description.setWordWrap(True)

        card_layout.addWidget(status_label)
        card_layout.addWidget(description)

        root_layout.addWidget(title)
        root_layout.addWidget(subtitle)
        root_layout.addWidget(status_card)
        root_layout.addStretch()

        self.setCentralWidget(central_widget)

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
                font-size: 17px;
            }

            QFrame#statusCard {
                background-color: #151c2f;
                border: 1px solid #26324d;
                border-radius: 16px;
            }

            QLabel#statusLabel {
                color: #5eead4;
                font-size: 22px;
                font-weight: 600;
            }

            QLabel#description {
                color: #cbd5e1;
                font-size: 15px;
            }
            """
        )