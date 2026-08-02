import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtWidgets import QApplication

from finradar.application.demo_mvp import DemoMvpController
from finradar.application.tax_profile_setup import (
    TaxProfileSetupService,
    tax_profile_context_from_snapshot,
)
from finradar.demo.scenario import DemoScenarioRepository
from finradar.infrastructure.database import (
    REGULATORY_ARCHIVE_DIRECTORY,
    SessionLocal,
    initialize_database,
)
from finradar.infrastructure.regulatory_inbox import RegulatoryInboxPaths
from finradar.infrastructure.regulatory_retention import RegulatoryArchiveRetention
from finradar.infrastructure.regulatory_trust_store import (
    SqlAlchemyRegulatoryTrustStore,
)
from finradar.infrastructure.tax_profile_repository import (
    SqlAlchemyTaxProfileRepository,
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

    repository = DemoScenarioRepository()
    controller = DemoMvpController(SessionLocal, repository=repository)
    tax_profile_service = TaxProfileSetupService(
        SqlAlchemyTaxProfileRepository(SessionLocal)
    )

    def tax_profile_context(scenario_id: str | None):
        selected = repository.load(scenario_id or "georgia_vat_pilot")
        return tax_profile_context_from_snapshot(
            selected.accounting_snapshot,
            effective_date=selected.as_of,
        )

    scenario = repository.load("georgia_vat_pilot")
    options = controller.options()
    window = MainWindow(
        horizon_days=scenario.horizon_days,
        forecast_runner=controller.run,
        demo_scenarios=tuple((item.scenario_id, item.title) for item in options),
        initial_scenario_id=scenario.scenario_id,
        demo_notice=scenario.fictional_notice,
        demo_notices={item.scenario_id: item.notice for item in options},
        history_provider=controller.history,
        history_loader=controller.load_history,
        tax_profile_service=tax_profile_service,
        tax_profile_context_provider=tax_profile_context,
        open_tax_settings_on_start=True,
    )
    window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
