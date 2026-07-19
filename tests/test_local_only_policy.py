import ast
import re
import tomllib
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APPLICATION_ROOT = PROJECT_ROOT / "src" / "finradar"
MONITOR_ROOT = PROJECT_ROOT / "packages" / "monitor" / "src" / "finradar_monitor"
CONTRACTS_ROOT = PROJECT_ROOT / "packages" / "contracts" / "src" / "finradar_contracts"

FORBIDDEN_IMPORTS = {
    "aiohttp",
    "boto3",
    "firebase_admin",
    "ftplib",
    "google.cloud",
    "grpc",
    "http.client",
    "httpx",
    "openai",
    "requests",
    "sentry_sdk",
    "smtplib",
    "socket",
    "urllib.request",
    "urllib3",
    "PySide6.QtNetwork",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebSockets",
}

FORBIDDEN_DEPENDENCIES = {
    "aiohttp",
    "boto3",
    "firebase-admin",
    "google-cloud",
    "grpcio",
    "httpx",
    "openai",
    "requests",
    "sentry-sdk",
    "urllib3",
}


def is_forbidden(module_name: str) -> bool:
    return any(
        module_name == prefix
        or module_name.startswith(f"{prefix}.")
        for prefix in FORBIDDEN_IMPORTS
    )


def test_application_has_no_network_imports() -> None:
    violations: list[str] = []

    for source_file in APPLICATION_ROOT.rglob("*.py"):
        tree = ast.parse(
            source_file.read_text(encoding="utf-8"),
            filename=str(source_file),
        )

        for node in ast.walk(tree):
            module_names: list[str] = []

            if isinstance(node, ast.Import):
                module_names.extend(
                    alias.name for alias in node.names
                )

            if isinstance(node, ast.ImportFrom) and node.module:
                module_names.append(node.module)

            for module_name in module_names:
                if is_forbidden(module_name):
                    relative_path = source_file.relative_to(
                        PROJECT_ROOT
                    )
                    violations.append(
                        f"{relative_path}:{node.lineno}: "
                        f"{module_name}"
                    )

    assert not violations, (
        "Forbidden network imports found:\n"
        + "\n".join(violations)
    )


def test_core_dependencies_have_no_network_clients() -> None:
    configuration = tomllib.loads(
        (PROJECT_ROOT / "pyproject.toml").read_text(
            encoding="utf-8"
        )
    )

    dependencies = configuration["project"]["dependencies"]

    dependency_names = {
        re.split(
            r"[<>=!~;\[]",
            requirement,
            maxsplit=1,
        )[0]
        .strip()
        .lower()
        .replace("_", "-")
        for requirement in dependencies
    }

    violations = sorted(
        dependency_names & FORBIDDEN_DEPENDENCIES
    )

    assert not violations, (
        "Forbidden network dependencies found: "
        + ", ".join(violations)
    )


def imported_modules(source_root: Path) -> list[tuple[Path, int, str]]:
    imports: list[tuple[Path, int, str]] = []
    for source_file in source_root.rglob("*.py"):
        tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend((source_file, node.lineno, alias.name) for alias in node.names)
            if isinstance(node, ast.ImportFrom) and node.module:
                imports.append((source_file, node.lineno, node.module))
    return imports


def test_core_and_monitor_do_not_import_each_other() -> None:
    violations: list[str] = []
    boundaries = (
        (APPLICATION_ROOT, "finradar_monitor"),
        (MONITOR_ROOT, "finradar"),
    )
    for source_root, forbidden_package in boundaries:
        for source_file, line_number, module_name in imported_modules(source_root):
            if module_name == forbidden_package or module_name.startswith(
                f"{forbidden_package}."
            ):
                relative_path = source_file.relative_to(PROJECT_ROOT)
                violations.append(f"{relative_path}:{line_number}: {module_name}")

    assert not violations, "Trust-boundary imports found:\n" + "\n".join(violations)


def test_contracts_are_neutral_and_have_no_network_clients() -> None:
    violations: list[str] = []
    for source_file, line_number, module_name in imported_modules(CONTRACTS_ROOT):
        is_project_runtime = (
            module_name == "finradar"
            or module_name.startswith("finradar.")
            or module_name == "finradar_monitor"
            or module_name.startswith("finradar_monitor.")
        )
        if is_project_runtime or is_forbidden(module_name):
            relative_path = source_file.relative_to(PROJECT_ROOT)
            violations.append(f"{relative_path}:{line_number}: {module_name}")

    assert not violations, "Non-neutral contract imports found:\n" + "\n".join(violations)


def test_runtime_distributions_are_declared_separately() -> None:
    core = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    contracts = tomllib.loads(
        (PROJECT_ROOT / "packages" / "contracts" / "pyproject.toml").read_text(
            encoding="utf-8"
        )
    )
    monitor = tomllib.loads(
        (PROJECT_ROOT / "packages" / "monitor" / "pyproject.toml").read_text(
            encoding="utf-8"
        )
    )

    assert core["project"]["name"] == "finradar"
    assert core["project"]["scripts"] == {"finradar": "finradar.main:main"}
    assert core["tool"]["setuptools"]["packages"]["find"]["include"] == [
        "finradar",
        "finradar.*",
    ]
    assert contracts["project"]["name"] == "finradar-contracts"
    assert contracts["project"]["dependencies"] == ["cryptography==49.0.0"]
    assert monitor["project"]["name"] == "finradar-monitor"
    assert monitor["project"]["scripts"] == {
        "finradar-monitor": "finradar_monitor.main:main"
    }
    assert monitor["project"]["dependencies"] == ["finradar-contracts==0.1.0"]
