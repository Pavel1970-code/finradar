# FinRadar

FinRadar is a desktop early warning system for small business financial risks.

The application combines accounting facts and versioned regulatory rules to produce deterministic, auditable financial forecasts.

## Development setup

FinRadar Core, the neutral contracts, and Regulatory Monitor are separate local
distributions. Install them together; installing only the repository root leaves
the console application without its contracts dependency.

macOS/Linux:

```bash
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/finradar
```

Windows PowerShell:

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\finradar.exe
```

Do not add `PYTHONPATH` as a normal launch requirement. The command must resolve
all three installed distributions in the same way as the packaged artifacts.

## Prototype goals

- Forecast cash availability for 30 days
- Detect potential liquidity gaps
- Show upcoming obligations
- Explain the source of each detected risk
- Preserve calculation inputs and results for audit

## Architecture principle

Artificial intelligence does not make financial calculations. Core calculations are deterministic, reproducible, and testable.

AI may later be used only to explain calculated results and retrieve relevant regulatory information.

## Privacy and data residency

FinRadar is designed as a local-first and on-premise financial system.

- Financial data remains on customer-controlled infrastructure.
- The standalone application works without internet access.
- Core calculations do not use cloud services.
- No customer financial data is sent to external AI providers.
- Multi-user deployments use a database server inside the company network.
- Telemetry, tracking, and automatic cloud uploads are disabled by design.

The current prototype stores fictional data in a local SQLite database.
Database encryption will be required before real financial data is imported.

See [ADR-001: Local-only financial data](docs/architecture/ADR-001-local-only-data.md)

The regulatory monitoring boundary and the production controls required before
network access is enabled are defined in
[ADR-006: Regulatory Monitor trust boundary](docs/architecture/ADR-006-regulatory-trust-boundary.md).

Core, the neutral boundary contracts, and Regulatory Monitor are maintained as
three independent Python distributions under the repository root and
`packages/`. Windows build and isolation inputs are documented in
[`packaging/windows`](packaging/windows/README.md) and
[`deployment/windows`](deployment/windows/README.md).

Signed regulatory ingestion, trusted-key rotation, quarantine, and replay
protection are defined in
[ADR-007: Signed regulatory package ingestion](docs/architecture/ADR-007-signed-regulatory-ingestion.md).

The read-only 1C adapter shell, canonical bank batches, deterministic bank-to-
accounting reconciliation, and the network decision for future bank APIs are
defined in
[ADR-008: Local integration SDK](docs/architecture/ADR-008-local-integration-sdk.md).

## Status

The offline MVP runs on four bundled scenarios.
It opens without seeding the prototype tables; press **Дать прогноз** to run the
accounting snapshot, bank reconciliation, fiscal rules, deterministic
forecast, stress calculation, and local audit-history pipeline.

The demo selector covers a base cash gap, incomplete recent bank data, and a
fictional fiscal-rate change with partial payment and delay consequences. A
fourth pilot applies a manually verified, narrow Georgian VAT rule to fictional
accounting data and exposes the calculation breakdown.

From an activated development environment:

```bash
finradar
```

Every bundled scenario is fixed to a documented analysis date so repeated runs
produce the same numerical result. The Georgian VAT pilot is not a complete tax
implementation and none of the scenarios may be used with real company data.

A function-by-function factual description of the current implementation,
including test evidence, Windows status, missing components, and known risks, is
available in
[PROJECT_FACTUAL_DESCRIPTION.md](docs/implementation/PROJECT_FACTUAL_DESCRIPTION.md).

The rate-free Georgian mandatory-obligation catalog and its payroll
double-counting rules are documented in
[GEORGIA_MANDATORY_OBLIGATIONS_CATALOG.md](docs/regulatory/GEORGIA_MANDATORY_OBLIGATIONS_CATALOG.md).
