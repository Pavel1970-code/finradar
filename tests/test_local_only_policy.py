import ast
import re
import tomllib
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APPLICATION_ROOT = PROJECT_ROOT / "src" / "finradar"

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