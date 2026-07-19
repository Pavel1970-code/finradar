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
- Alembic baseline and additive synchronization-history migration for both new
  databases and existing prototype databases without deleting business data.
- Append-only synchronization runs with canonical JSON source snapshots,
  SHA-256 integrity hashes, and database triggers preventing snapshot updates or
  deletion.
- Snapshot decoding with integrity verification for later audit reproduction.
- Canonical accounting metrics and payment-event statuses, settled amounts, and
  stable fiscal obligation keys in connector snapshots.
- Deterministic fiscal rule lifecycle and applicability outcomes: `applied`,
  `not_applicable`, and `unresolved` with explicit missing fields.
- Initial fictional percentage obligation calculation from a named accounting
  metric, including rule version, source, formula explanation, and due date.
- Reconciliation against existing, settled, partially paid, cancelled, and
  duplicate payment-calendar events before they enter the cash forecast.
- Unified analytical pipeline combining connector facts, fiscal obligations, and
  the existing liquidity forecast.
- Fiscal consequence states `accrued`, `calculated`, `contingent`, and
  `unresolved`, with links back to the originating obligation.
- Daily late-payment penalty calculation with grace periods, changing rate
  segments, full coverage validation, and source traceability.
- Formalized fixed or percentage fine rules with minimum/maximum limits,
  obligation scope, and authority-decision requirements.
- Separate primary and stress forecasts: accrued/calculated charges affect the
  primary forecast, while contingent exposure affects only the stress scenario.
- Recognition of fiscal charges already supplied by accounting data to prevent
  duplicate generated penalties or fines.
- Immutable fiscal rule definitions stored as canonical JSON with SHA-256 hashes
  and unique `rule_id`/version identities.
- Append-only lifecycle events enforcing `candidate -> validated -> reviewed ->
  active -> superseded`; direct candidate activation is rejected.
- Automatic supersession of an older active version when a reviewed newer
  version is activated.
- Typed loading of active obligation, penalty, and fine rules into the desktop
  analysis pipeline.
- Immutable fiscal-analysis history linked to source synchronization runs and
  containing primary/stress forecasts, applicability, reconciliation,
  consequences, horizon, and algorithm version.
- Backward-compatible reading of version 1 snapshots; new snapshots use schema
  version 2.
- ADR for connector boundaries and regulatory network isolation.

## Verification

Run with the project virtual environment:

```bash
.venv/bin/python -m ruff check .
.venv/bin/python -m pytest -q
```

Latest result: Ruff passed; 44 tests passed, including fiscal rule lifecycle,
version supersession, immutable analysis history, fiscal applicability,
calculation, reconciliation, migration, snapshot compatibility, immutability,
penalty rate changes and gaps, conditional fines, stress scenarios, round-trip,
and UI smoke tests.

## Current limitations

- Regulatory source documents and AI extraction candidates are not ingested yet;
  the rule registry accepts structured candidates but has no monitoring adapter.
- The fiscal engine supports only a fictional percentage rule and is not a real
  tax implementation.
- Penalty and fine structures are generic and tested only with fictional rules;
  no real jurisdictional formula has been activated.
- No network access has been added.
- No concrete 1C adapter has been selected or implemented.

## Next implementation slice

1. Add the table of accounting and generated fiscal events, including accrued,
   calculated, and contingent consequences.
2. Add a regulatory rule registry screen with lifecycle and source evidence.
3. Extend readiness checks with source-level rejected records and connector
   diagnostics.
4. Add a synchronization and fiscal-analysis history screen.
5. Add explicit company jurisdiction and tax-regime fields through a migration;
   until then the current prototype correctly reports limited fiscal readiness.
