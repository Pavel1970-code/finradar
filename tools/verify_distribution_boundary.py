"""Verify package contents after building the three FinRadar wheels."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from email.parser import BytesParser
from pathlib import Path
from zipfile import ZipFile


@dataclass(frozen=True)
class WheelPolicy:
    name: str
    required_packages: frozenset[str]
    forbidden_packages: frozenset[str]
    required_dependencies: frozenset[str] = frozenset()


POLICIES = {
    "core": WheelPolicy(
        name="Core",
        required_packages=frozenset({"finradar"}),
        forbidden_packages=frozenset({"finradar_monitor", "finradar_contracts"}),
        required_dependencies=frozenset({"finradar-contracts"}),
    ),
    "contracts": WheelPolicy(
        name="Contracts",
        required_packages=frozenset({"finradar_contracts"}),
        forbidden_packages=frozenset({"finradar", "finradar_monitor"}),
        required_dependencies=frozenset({"cryptography"}),
    ),
    "monitor": WheelPolicy(
        name="Monitor",
        required_packages=frozenset({"finradar_monitor"}),
        forbidden_packages=frozenset({"finradar", "finradar_contracts"}),
        required_dependencies=frozenset({"finradar-contracts"}),
    ),
}


class BoundaryVerificationError(RuntimeError):
    """A built distribution violates the intended package boundary."""


def verify_wheel(wheel_path: Path, role: str) -> None:
    policy = POLICIES[role]
    with ZipFile(wheel_path) as wheel:
        members = set(wheel.namelist())
        metadata_names = [name for name in members if name.endswith(".dist-info/METADATA")]
        if len(metadata_names) != 1:
            raise BoundaryVerificationError(
                f"{policy.name} wheel must contain exactly one METADATA file"
            )
        metadata = BytesParser().parsebytes(wheel.read(metadata_names[0]))

    missing = sorted(
        package for package in policy.required_packages if not _contains_package(members, package)
    )
    forbidden = sorted(
        package for package in policy.forbidden_packages if _contains_package(members, package)
    )
    dependencies = {
        _dependency_name(value)
        for value in metadata.get_all("Requires-Dist", [])
    }
    missing_dependencies = sorted(policy.required_dependencies - dependencies)

    errors: list[str] = []
    if missing:
        errors.append(f"missing packages: {', '.join(missing)}")
    if forbidden:
        errors.append(f"forbidden packages: {', '.join(forbidden)}")
    if missing_dependencies:
        errors.append(f"missing dependencies: {', '.join(missing_dependencies)}")
    if errors:
        raise BoundaryVerificationError(
            f"{policy.name} wheel boundary violation: {'; '.join(errors)}"
        )


def _contains_package(members: set[str], package: str) -> bool:
    return any(member.startswith(f"{package}/") for member in members)


def _dependency_name(requirement: str) -> str:
    characters: list[str] = []
    for character in requirement:
        if character in " <>=!~;[":
            break
        characters.append(character)
    return "".join(characters).strip().casefold().replace("_", "-")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core", required=True, type=Path)
    parser.add_argument("--contracts", required=True, type=Path)
    parser.add_argument("--monitor", required=True, type=Path)
    arguments = parser.parse_args()

    verify_wheel(arguments.core, "core")
    verify_wheel(arguments.contracts, "contracts")
    verify_wheel(arguments.monitor, "monitor")
    print("FinRadar wheel boundaries verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
