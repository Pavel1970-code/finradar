from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_development_requirements_install_all_local_distributions() -> None:
    lines = tuple(
        line.strip()
        for line in (PROJECT_ROOT / "requirements-dev.txt")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )

    assert lines == (
        "-e ./packages/contracts",
        "-e .[dev]",
        "-e ./packages/monitor",
    )


def test_readme_uses_console_entry_point_without_pythonpath() -> None:
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")

    assert ".venv/bin/python -m pip install -r requirements-dev.txt" in readme
    assert ".venv/bin/finradar" in readme
    assert "PYTHONPATH=src" not in readme
