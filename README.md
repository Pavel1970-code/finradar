# FinRadar

FinRadar is a desktop early warning system for small business financial risks.

The application combines accounting facts and versioned regulatory rules to produce deterministic, auditable financial forecasts.

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

Early desktop prototype under active development.

A function-by-function factual description of the current implementation,
including test evidence, Windows status, missing components, and known risks, is
available in
[PROJECT_FACTUAL_DESCRIPTION.md](docs/implementation/PROJECT_FACTUAL_DESCRIPTION.md).
