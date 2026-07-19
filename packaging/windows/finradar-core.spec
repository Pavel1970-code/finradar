# Build on Windows only: python -m PyInstaller packaging/windows/finradar-core.spec

import sys
from pathlib import Path


SPEC_DIRECTORY = Path(SPEC).resolve().parent
PROJECT_ROOT = SPEC_DIRECTORY.parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from tools.frozen_boundary import assert_analysis_boundary


CORE_FORBIDDEN_MODULES = {
    "PySide6.QtNetwork",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebSockets",
    "aiohttp",
    "finradar_monitor",
    "ftplib",
    "http.client",
    "httpx",
    "openai",
    "requests",
    "smtplib",
    "socket",
    "urllib.request",
    "urllib3",
}

analysis = Analysis(
    [str(PROJECT_ROOT / "src" / "finradar" / "main.py")],
    pathex=[
        str(PROJECT_ROOT / "src"),
        str(PROJECT_ROOT / "packages" / "contracts" / "src"),
    ],
    binaries=[],
    datas=[
        (str(PROJECT_ROOT / "alembic.ini"), "."),
        (str(PROJECT_ROOT / "migrations"), "migrations"),
        (
            str(PROJECT_ROOT / "src" / "finradar" / "demo" / "scenarios"),
            "finradar/demo/scenarios",
        ),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=sorted(CORE_FORBIDDEN_MODULES),
    noarchive=False,
    optimize=1,
)

assert_analysis_boundary(
    analysis,
    artifact_name="FinRadarCore",
    required_modules={"finradar", "finradar_contracts"},
    forbidden_modules=CORE_FORBIDDEN_MODULES,
    forbidden_binary_fragments={"_socket", "Qt6Network"},
)

archive = PYZ(analysis.pure)

executable = EXE(
    archive,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="FinRadarCore",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

bundle = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="FinRadarCore",
)
