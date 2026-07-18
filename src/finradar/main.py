import sys

from PySide6.QtWidgets import QApplication

from finradar.application.forecast_service import (
    load_company_forecast,
)
from finradar.infrastructure.database import initialize_database
from finradar.ui.main_window import MainWindow


def main() -> int:
    initialize_database()
    dashboard = load_company_forecast()

    app = QApplication(sys.argv)
    app.setApplicationName("FinRadar")
    app.setOrganizationName("FinRadar")
    app.setStyle("Fusion")

    window = MainWindow(dashboard=dashboard)
    window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())