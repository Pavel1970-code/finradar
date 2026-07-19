import argparse
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from PySide6.QtWidgets import QApplication

from finradar.application.synchronization_service import synchronize_and_forecast
from finradar.infrastructure.connectors.prototype_database import PrototypeDatabaseConnector
from finradar.infrastructure.database import (
    REGULATORY_ARCHIVE_DIRECTORY,
    SessionLocal,
    initialize_database,
)
from finradar.infrastructure.synchronization_history import (
    SqlAlchemySynchronizationHistory,
)
from finradar.infrastructure.fiscal_analysis_history import (
    SqlAlchemyFiscalAnalysisHistory,
)
from finradar.infrastructure.fiscal_rule_registry import SqlAlchemyFiscalRuleRegistry
from finradar.infrastructure.regulatory_trust_store import (
    SqlAlchemyRegulatoryTrustStore,
)
from finradar.infrastructure.regulatory_inbox import RegulatoryInboxPaths
from finradar.infrastructure.regulatory_retention import RegulatoryArchiveRetention
from finradar.ui.main_window import MainWindow
from finradar_contracts import decode_trust_record


def main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FinRadar local financial early warning")
    parser.add_argument("--bootstrap-regulatory-trust", type=Path)
    parser.add_argument(
        "--bootstrap-source",
        default="signed FinRadar installer",
    )
    options = parser.parse_args(arguments)
    initialize_database()
    if options.bootstrap_regulatory_trust is not None:
        record_path = options.bootstrap_regulatory_trust
        if record_path.is_symlink() or not record_path.is_file():
            parser.error("regulatory trust record must be a regular file")
        record = decode_trust_record(record_path.read_bytes())
        SqlAlchemyRegulatoryTrustStore(SessionLocal).bootstrap_initial_key(
            public_key_record=record,
            source=options.bootstrap_source,
            reason="Provisioned by the signed application installer.",
        )
        print(f"Regulatory trust initialized: {record['key_id']}.")
        return 0

    RegulatoryArchiveRetention(
        SessionLocal,
        paths=RegulatoryInboxPaths.under(REGULATORY_ARCHIVE_DIRECTORY),
    ).enforce()

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
