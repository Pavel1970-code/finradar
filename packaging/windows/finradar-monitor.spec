# Build on Windows only: python -m PyInstaller packaging/windows/finradar-monitor.spec

import sys
from pathlib import Path


SPEC_DIRECTORY = Path(SPEC).resolve().parent
PROJECT_ROOT = SPEC_DIRECTORY.parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from tools.frozen_boundary import assert_analysis_boundary


MONITOR_FORBIDDEN_MODULES = {
    "PySide6",
    "alembic",
    "finradar",
    "pydantic",
    "sqlalchemy",
}

analysis = Analysis(
    [
        str(
            PROJECT_ROOT
            / "packages"
            / "monitor"
            / "src"
            / "finradar_monitor"
            / "main.py"
        )
    ],
    pathex=[
        str(PROJECT_ROOT / "packages" / "monitor" / "src"),
        str(PROJECT_ROOT / "packages" / "contracts" / "src"),
    ],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=sorted(MONITOR_FORBIDDEN_MODULES),
    noarchive=False,
    optimize=1,
)

assert_analysis_boundary(
    analysis,
    artifact_name="FinRadarMonitor",
    required_modules={"finradar_contracts", "finradar_monitor"},
    forbidden_modules=MONITOR_FORBIDDEN_MODULES,
)

archive = PYZ(analysis.pure)

executable = EXE(
    archive,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="FinRadarMonitor",
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
    name="FinRadarMonitor",
)
