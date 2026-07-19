"""Entry point for the isolated regulatory monitor process."""

from finradar_monitor.paths import MonitorPaths
from finradar_monitor.storage import RegulatoryStorage


def main() -> int:
    paths = MonitorPaths.from_environment()
    paths.create()
    storage = RegulatoryStorage(paths.database_path)
    storage.initialize()
    print(
        "FinRadar Regulatory Monitor initialized. "
        f"Public documents: {storage.count_documents()}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
