# Windows artifact build

PyInstaller is not a cross-compiler. Build the Windows executables on a clean
Windows runner with Python 3.13.

```powershell
python -m venv .build-venv
.build-venv\Scripts\python -m pip install packages/contracts
.build-venv\Scripts\python -m pip install .
.build-venv\Scripts\python -m pip install packages/monitor
.build-venv\Scripts\python -m pip install -r packaging/windows/requirements.txt
.\packaging\windows\Build-Artifacts.ps1 -Python .build-venv\Scripts\python.exe
```

The two spec files perform build-time dependency-graph assertions:

- Core must contain `finradar` and the neutral contract but no Monitor or
  network-client modules. `_socket` and `Qt6Network` binaries are rejected.
- Monitor must contain Monitor and the neutral contract but no Core, PySide,
  SQLAlchemy, Alembic, or Pydantic runtime.
- The builds are independent and deliberately do not use PyInstaller `MERGE`.

Core bundles `alembic.ini` and migrations as read-only resources. In a frozen
build its mutable SQLite database is created under the platform user-data
directory rather than beside the executable.

Wheel boundaries can be checked independently with:

```powershell
python tools/verify_distribution_boundary.py `
  --core path\to\finradar.whl `
  --contracts path\to\finradar_contracts.whl `
  --monitor path\to\finradar_monitor.whl
```

Code signing and installer generation are required release steps and are not
performed by the repository build script because signing keys must not be stored
in source control.
