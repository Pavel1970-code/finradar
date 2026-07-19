"""Filesystem locations owned exclusively by the regulatory monitor."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


DATA_DIRECTORY_ENV = "FINRADAR_MONITOR_DATA_DIR"


@dataclass(frozen=True)
class MonitorPaths:
    data_directory: Path
    database_path: Path
    outbox_directory: Path

    @classmethod
    def from_environment(cls) -> MonitorPaths:
        configured = os.environ.get(DATA_DIRECTORY_ENV)
        data_directory = (
            Path(configured).expanduser()
            if configured
            else _default_data_directory()
        )
        data_directory = data_directory.resolve()
        return cls(
            data_directory=data_directory,
            database_path=data_directory / "regulatory_monitor.db",
            outbox_directory=data_directory / "outbox",
        )

    def create(self) -> None:
        self.data_directory.mkdir(parents=True, exist_ok=True)
        self.outbox_directory.mkdir(parents=True, exist_ok=True)


def _default_data_directory() -> Path:
    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "FinRadarMonitor"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "FinRadarMonitor"
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home:
        return Path(xdg_data_home) / "finradar-monitor"
    return Path.home() / ".local" / "share" / "finradar-monitor"
