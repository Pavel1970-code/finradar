from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from tools.verify_distribution_boundary import BoundaryVerificationError, verify_wheel


def make_wheel(
    path: Path,
    *,
    distribution: str,
    packages: set[str],
    dependencies: tuple[str, ...] = (),
) -> Path:
    metadata_lines = [
        "Metadata-Version: 2.4",
        f"Name: {distribution}",
        "Version: 0.1.0",
    ]
    metadata_lines.extend(f"Requires-Dist: {dependency}" for dependency in dependencies)
    metadata = "\n".join(metadata_lines) + "\n"
    with ZipFile(path, "w", ZIP_DEFLATED) as wheel:
        for package in packages:
            wheel.writestr(f"{package}/__init__.py", "")
        wheel.writestr(f"{distribution}-0.1.0.dist-info/METADATA", metadata)
    return path


def test_independent_wheel_policies_accept_expected_contents(tmp_path: Path) -> None:
    core = make_wheel(
        tmp_path / "core.whl",
        distribution="finradar",
        packages={"finradar"},
        dependencies=("finradar-contracts==0.1.0",),
    )
    contracts = make_wheel(
        tmp_path / "contracts.whl",
        distribution="finradar_contracts",
        packages={"finradar_contracts"},
    )
    monitor = make_wheel(
        tmp_path / "monitor.whl",
        distribution="finradar_monitor",
        packages={"finradar_monitor"},
        dependencies=("finradar-contracts==0.1.0",),
    )

    verify_wheel(core, "core")
    verify_wheel(contracts, "contracts")
    verify_wheel(monitor, "monitor")


def test_monitor_wheel_rejects_embedded_core(tmp_path: Path) -> None:
    monitor = make_wheel(
        tmp_path / "monitor.whl",
        distribution="finradar_monitor",
        packages={"finradar", "finradar_monitor"},
        dependencies=("finradar-contracts==0.1.0",),
    )

    with pytest.raises(BoundaryVerificationError, match="forbidden packages: finradar"):
        verify_wheel(monitor, "monitor")
