"""Entry point for the isolated regulatory monitor process."""

import argparse
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

from finradar_monitor.paths import MonitorPaths
from finradar_monitor.signing_keys import MonitorSigningKeyStore
from finradar_monitor.storage import RegulatoryStorage


def main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FinRadar public regulatory monitor")
    parser.add_argument("--data-directory", type=Path)
    parser.add_argument("--outbox-directory", type=Path)
    parser.add_argument("--initialize-signing-key", action="store_true")
    parser.add_argument("--public-key-record", type=Path)
    options = parser.parse_args(arguments)
    if options.initialize_signing_key != (options.public_key_record is not None):
        parser.error(
            "--initialize-signing-key and --public-key-record must be used together"
        )

    paths = MonitorPaths.from_configuration(
        data_directory=options.data_directory,
        outbox_directory=options.outbox_directory,
    )
    paths.create()
    storage = RegulatoryStorage(paths.database_path)
    storage.initialize()
    if options.initialize_signing_key:
        record_path = options.public_key_record.resolve()
        if not record_path.is_relative_to(paths.outbox_directory):
            parser.error("public key record must be written inside the Monitor outbox")
        key = MonitorSigningKeyStore(paths.signing_key_directory).initialize_bootstrap_key(
            record_path,
            at_time=datetime.now(timezone.utc),
        )
        print(f"Monitor signing key initialized: {key.key_id}.")
        return 0
    print(
        "FinRadar Regulatory Monitor initialized. "
        f"Public documents: {storage.count_documents()}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
