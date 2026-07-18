import sys
from datetime import date

from PySide6.QtWidgets import QApplication

from finradar.application.synchronization_service import synchronize_and_forecast
from finradar.infrastructure.connectors.prototype_database import PrototypeDatabaseConnector
from finradar.infrastructure.database import SessionLocal, initialize_database
from finradar.infrastructure.synchronization_history import (
    SqlAlchemySynchronizationHistory,
)
from finradar.ui.main_window import MainWindow


def main() -> int:
    initialize_database()
    horizon_days = 30
    analysis = synchronize_and_forecast(
        PrototypeDatabaseConnector(SessionLocal),
        as_of=date.today(),
        horizon_days=horizon_days,
        recorder=SqlAlchemySynchronizationHistory(SessionLocal),
    )

    app = QApplication(sys.argv)
    app.setApplicationName("FinRadar")
    app.setOrganizationName("FinRadar")
    app.setStyle("Fusion")

    window = MainWindow(analysis=analysis, horizon_days=horizon_days)
    window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
