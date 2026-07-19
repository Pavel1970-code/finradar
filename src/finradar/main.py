import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtWidgets import QApplication

from finradar.application.forecast_facade import (
    ForecastApplicationFacade,
    ForecastRunConfiguration,
)
from finradar.demo.scenario import DemoScenarioRepository
from finradar.infrastructure.bank_synchronization_history import (
    SqlAlchemyBankSynchronizationHistory,
)
from finradar.infrastructure.connectors.scenario import (
    ScenarioAccountingConnector,
    ScenarioBankConnector,
)
from finradar.infrastructure.database import (
    REGULATORY_ARCHIVE_DIRECTORY,
    SessionLocal,
    initialize_database,
)
from finradar.infrastructure.demo_fiscal_rules import DemoFiscalRuleBootstrapper
from finradar.infrastructure.fiscal_analysis_history import (
    SqlAlchemyFiscalAnalysisHistory,
)
from finradar.infrastructure.fiscal_rule_registry import SqlAlchemyFiscalRuleRegistry
from finradar.infrastructure.regulatory_inbox import RegulatoryInboxPaths
from finradar.infrastructure.regulatory_retention import RegulatoryArchiveRetention
from finradar.infrastructure.regulatory_trust_store import (
    SqlAlchemyRegulatoryTrustStore,
)
from finradar.infrastructure.synchronization_history import (
    SqlAlchemySynchronizationHistory,
)
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

    app = QApplication(sys.argv)
    app.setApplicationName("FinRadar")
    app.setOrganizationName("FinRadar")
    app.setStyle("Fusion")

    scenario = DemoScenarioRepository().load("base_cash_gap")
    rule_bootstrapper = DemoFiscalRuleBootstrapper(
        SqlAlchemyFiscalRuleRegistry(SessionLocal)
    )
    facade = ForecastApplicationFacade(
        ScenarioAccountingConnector(scenario),
        configuration=ForecastRunConfiguration(
            as_of=scenario.as_of,
            horizon_days=scenario.horizon_days,
            stress_overdue_days=scenario.stress_overdue_days,
        ),
        rule_provider=lambda: rule_bootstrapper.ensure(scenario.fiscal_rules),
        bank_connector=ScenarioBankConnector(scenario),
        synchronization_recorder=SqlAlchemySynchronizationHistory(SessionLocal),
        bank_recorder=SqlAlchemyBankSynchronizationHistory(SessionLocal),
        analysis_recorder=SqlAlchemyFiscalAnalysisHistory(SessionLocal),
        violation_events=scenario.violation_events,
    )
    window = MainWindow(
        horizon_days=scenario.horizon_days,
        forecast_runner=facade.run,
        demo_notice=scenario.fictional_notice,
    )
    window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
