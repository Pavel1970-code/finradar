import os
from datetime import date

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel

from finradar.application.synchronization_service import synchronize_and_forecast
from finradar.domain.financial_snapshot import DatasetKind
from finradar.infrastructure.connectors.demo import DemoAccountingConnector
from finradar.ui.main_window import MainWindow


AS_OF = date(2026, 7, 18)


def make_application() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_limited_report_and_forecast_are_visible_together() -> None:
    app = make_application()
    outcome = synchronize_and_forecast(
        DemoAccountingConnector(
            as_of=AS_OF,
            unavailable_datasets=frozenset({DatasetKind.PAYMENT_CALENDAR}),
        ),
        as_of=AS_OF,
    )

    window = MainWindow(analysis=outcome, horizon_days=30)
    window.show()
    app.processEvents()

    assert window.findChild(QLabel, "readinessStatus").text() == (
        "Анализ возможен с ограничениями"
    )
    assert any(
        label.text() == "Первый кассовый разрыв"
        for label in window.findChildren(QLabel, "metricCaption")
    )
    window.close()


def test_blocked_report_hides_forecast_metrics() -> None:
    app = make_application()
    outcome = synchronize_and_forecast(
        DemoAccountingConnector(
            as_of=AS_OF,
            unavailable_datasets=frozenset({DatasetKind.ACCOUNT_BALANCES}),
        ),
        as_of=AS_OF,
    )

    window = MainWindow(analysis=outcome, horizon_days=30)
    window.show()
    app.processEvents()

    assert window.findChild(QLabel, "readinessStatus").text() == "Анализ заблокирован"
    assert window.findChildren(QLabel, "metricCaption") == []
    window.close()

