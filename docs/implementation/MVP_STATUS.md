# FinRadar implementation status

Updated: 2026-07-18

## Product direction

FinRadar is a Windows desktop early-warning application. It reads accounting
facts and a payment calendar through read-only connectors, reports gaps in the
available information, and performs deterministic cash and fiscal calculations.

Customer financial data remains on customer-controlled infrastructure. External
network access is reserved for an isolated regulatory-monitoring module that has
no access to accounting data. AI may extract candidate facts from public fiscal
documents and explain verified results, but it does not activate rules or
calculate amounts.

## Implemented

- PySide6 desktop dashboard backed by a local SQLite prototype database.
- Deterministic daily cash forecast and liquidity-gap detection.
- SQLAlchemy models for companies, cash accounts, and cash-flow items.
- Repeatable fictional demo dataset.
- Local-only architecture policy and network dependency tests.
- Canonical connector-facing financial snapshot for company profile, balances,
  accounting facts, and payment-calendar events.
- Explicit distinction between an available empty dataset and an unavailable
  dataset.
- Read-only accounting connector protocol and capability declaration.
- Deterministic demo/reference connector supplying fictional company data,
  account balances, and payment-calendar events.
- Application synchronization service that verifies connector declarations,
  runs preflight checks, and builds a forecast only when data are sufficient.
- Data-readiness report with `ready`, `limited`, and `blocked` outcomes.
- Initial checks for unavailable balances, empty balances, stale balances,
  unavailable payment calendar, jurisdiction, tax regime, and incompatible
  currencies.
- End-to-end reference scenarios for complete, limited, and blocked data.
- Read-only adapter from the current prototype SQLite schema to the canonical
  connector snapshot.
- Scrollable desktop preflight report showing source, supplied datasets,
  limitations, blocking errors, and their forecast impact in Russian.
- The desktop dashboard and preflight report now use the same synchronized
  snapshot, avoiding mixed-source results.
- ADR for connector boundaries and regulatory network isolation.

## Verification

Run with the project virtual environment:

```bash
.venv/bin/python -m ruff check .
.venv/bin/python -m pytest -q
```

Latest result: Ruff passed; 14 tests passed, including UI smoke tests.

## Current limitations

- No synchronization journal or persisted source snapshots exist yet.
- No regulatory document, candidate-rule, reviewed-rule, or active-rule models
  exist yet.
- No network access has been added.
- No concrete 1C adapter has been selected or implemented.

## Next implementation slice

1. Define persisted synchronization runs and immutable source snapshots before
   implementing a concrete 1C adapter.
2. Extend readiness checks with source-level rejected records and connector
   diagnostics.
3. Add the table of source events and make forecast causes visible.
4. Add explicit company jurisdiction and tax-regime fields through a migration;
   until then the current prototype correctly reports limited fiscal readiness.
