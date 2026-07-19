import sys
from datetime import date

from PySide6.QtWidgets import QApplication

from finradar.application.synchronization_service import synchronize_and_forecast
from finradar.infrastructure.connectors.prototype_database import PrototypeDatabaseConnector
from finradar.infrastructure.database import SessionLocal, initialize_database
from finradar.infrastructure.synchronization_history import (
    SqlAlchemySynchronizationHistory,
)
from finradar.infrastructure.fiscal_analysis_history import (
    SqlAlchemyFiscalAnalysisHistory,
)
from finradar.infrastructure.fiscal_rule_registry import SqlAlchemyFiscalRuleRegistry
from finradar.ui.main_window import MainWindow


def main() -> int:
    initialize_database()
    horizon_days = 30
    active_rules = SqlAlchemyFiscalRuleRegistry(SessionLocal).load_active_ruleset()
    analysis = synchronize_and_forecast(
        PrototypeDatabaseConnector(SessionLocal),
        as_of=date.today(),
        horizon_days=horizon_days,
        recorder=SqlAlchemySynchronizationHistory(SessionLocal),
        analysis_recorder=SqlAlchemyFiscalAnalysisHistory(SessionLocal),
        fiscal_rules=active_rules.obligation_rules,
        penalty_rules=active_rules.penalty_rules,
        fine_rules=active_rules.fine_rules,
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
