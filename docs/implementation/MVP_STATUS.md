# FinRadar implementation status

Updated: 2026-07-19

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
- Separate `finradar-monitor` process entry point with its own platform data
  directory, `regulatory_monitor.db`, and public-package outbox.
- Neutral standard-library-only `finradar_contracts` package shared across the
  trust boundary without importing either runtime.
- Strict one-way regulatory package format with byte/item limits, duplicate-key
  rejection, source evidence links, public-data field controls, and canonical
  SHA-256 integrity verification.
- Exact official-source HTTPS allowlist for Matsne, Revenue Service, Ministry of
  Finance, and National Bank hosts, including rejection of deceptive hostnames,
  credentials, and non-standard ports.
- Offline Core inbound validator that accepts JSON packages only and does not
  activate imported candidates.
- Dependency-direction tests proving that Core and Monitor do not import each
  other, while Core remains free of network clients.
- ADR-006 threat model separating the current development boundary from the OS
  controls still required before network access can be enabled.

## Verification

Run with the project virtual environment:

```bash
.venv/bin/python -m ruff check .
.venv/bin/python -m pytest -q
```

Latest result: Ruff passed; 59 tests passed, including the regulatory trust
boundary, malformed/tampered package rejection, official-source policy, separate
monitor storage, fiscal rule lifecycle,
version supersession, immutable analysis history, fiscal applicability,
calculation, reconciliation, migration, snapshot compatibility, immutability,
penalty rate changes and gaps, conditional fines, stress scenarios, round-trip,
and UI smoke tests.

## Current limitations

- Regulatory network retrieval and AI extraction are not implemented yet. The
  Monitor boundary, public storage, exchange contract, and Core validator exist,
  but no real source is downloaded.
- The development package currently exposes separate process entry points but is
  not yet split into production Core/Monitor build artifacts.
- Windows service identities, filesystem ACLs, outbound firewall enforcement,
  package signatures, quarantine, and replay protection are not implemented.
- The fiscal engine supports only a fictional percentage rule and is not a real
  tax implementation.
- Penalty and fine structures are generic and tested only with fictional rules;
  no real jurisdictional formula has been activated.
- No network access has been added.
- No concrete 1C adapter has been selected or implemented.

## Next implementation slice

1. Split Core and Monitor into independently built Windows artifacts and enforce
   distinct runtime identities, filesystem ACLs, and firewall policy.
2. Add signed manifests, trusted-key rotation, package quarantine, replay
   protection, and import audit history.
3. Implement a constrained downloader that revalidates the allowlist after every
   redirect, then connect one stable official Georgian source without AI.
4. Map accepted public packages into the existing candidate-rule lifecycle and
   add a source-evidence review screen.
5. Add source-level rejected-record diagnostics and the user-facing data quality
   report for accounting and bank inputs.
