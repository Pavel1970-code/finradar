"""Build-time assertions for frozen artifact dependency graphs."""

from collections.abc import Iterable
from typing import Any


def assert_analysis_boundary(
    analysis: Any,
    *,
    artifact_name: str,
    required_modules: Iterable[str],
    forbidden_modules: Iterable[str],
    forbidden_binary_fragments: Iterable[str] = (),
) -> None:
    module_names = {entry[0] for entry in analysis.pure}
    missing = [name for name in required_modules if not _contains(module_names, name)]
    forbidden = [name for name in forbidden_modules if _contains(module_names, name)]

    binary_names = {
        str(field).casefold()
        for entry in analysis.binaries
        for field in entry[:2]
    }
    forbidden_binaries = [
        fragment
        for fragment in forbidden_binary_fragments
        if any(fragment.casefold() in binary_name for binary_name in binary_names)
    ]

    errors: list[str] = []
    if missing:
        errors.append(f"missing required modules: {', '.join(sorted(missing))}")
    if forbidden:
        errors.append(f"forbidden modules: {', '.join(sorted(forbidden))}")
    if forbidden_binaries:
        errors.append(
            "forbidden binaries: " + ", ".join(sorted(forbidden_binaries))
        )
    if errors:
        raise RuntimeError(f"{artifact_name} boundary violation: {'; '.join(errors)}")


def _contains(module_names: set[str], package_name: str) -> bool:
    return any(
        module_name == package_name or module_name.startswith(f"{package_name}.")
        for module_name in module_names
    )
