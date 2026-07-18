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

## Status

Early desktop prototype under active developmen.
