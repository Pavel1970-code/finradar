"""Atomic export of validated public-only packages to the monitor outbox."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from finradar_contracts import build_regulatory_package, encode_regulatory_package


def export_regulatory_package(
    *,
    outbox_directory: Path,
    sources: Iterable[Mapping[str, Any]],
    candidates: Iterable[Mapping[str, Any]],
) -> Path:
    outbox = outbox_directory.resolve()
    outbox.mkdir(parents=True, exist_ok=True)
    package = build_regulatory_package(sources=sources, candidates=candidates)
    encoded = encode_regulatory_package(package)
    destination = outbox / f"{package['package_id']}.finradar-regulatory.json"

    descriptor, temporary_name = tempfile.mkstemp(
        dir=outbox,
        prefix=".regulatory-",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        temporary_path.replace(destination)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
    return destination
