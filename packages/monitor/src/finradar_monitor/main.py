"""Entry point for the isolated regulatory monitor process."""

import argparse
from collections.abc import Sequence
from pathlib import Path

from finradar_monitor.paths import MonitorPaths
from finradar_monitor.storage import RegulatoryStorage


def main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FinRadar public regulatory monitor")
    parser.add_argument("--data-directory", type=Path)
    parser.add_argument("--outbox-directory", type=Path)
    options = parser.parse_args(arguments)

    paths = MonitorPaths.from_configuration(
        data_directory=options.data_directory,
        outbox_directory=options.outbox_directory,
    )
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
