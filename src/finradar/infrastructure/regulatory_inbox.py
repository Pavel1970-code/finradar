"""Core-side validation boundary for public regulatory packages."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from finradar_contracts import (
    MAX_PACKAGE_BYTES,
    RegulatoryPackageError,
    decode_regulatory_package,
)


class RegulatoryInboxError(ValueError):
    """A package cannot safely cross from the monitor into Core."""


def validate_regulatory_package_file(package_path: Path) -> dict[str, Any]:
    path = package_path.resolve(strict=True)
    if not path.is_file():
        raise RegulatoryInboxError("regulatory package must be a regular file")
    if path.suffix.casefold() != ".json":
        raise RegulatoryInboxError("regulatory package must be a JSON file")

    size = path.stat().st_size
    if size > MAX_PACKAGE_BYTES:
        raise RegulatoryInboxError("regulatory package exceeds the maximum allowed size")

    try:
        return decode_regulatory_package(path.read_bytes())
    except RegulatoryPackageError as error:
        raise RegulatoryInboxError(str(error)) from error
