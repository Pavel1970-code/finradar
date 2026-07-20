# FinRadar implementation status

Updated: 2026-07-20

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
- Backward-compatible reading of version 1 and 2 snapshots; new snapshots use
  schema version 3 with source issues, cursors, bank links, and event provenance.
- ADR for connector boundaries and regulatory network isolation.
- Separate `finradar-monitor` process entry point with its own platform data
  directory, `regulatory_monitor.db`, and public-package outbox.
- Neutral `finradar_contracts` package shared across the trust boundary without
  importing either runtime; its only external dependency is the Ed25519
  cryptographic implementation.
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
- Three independent Python distributions: Core, neutral Contracts, and Monitor.
  Actual wheel inspection proves that Core and Monitor do not embed each other.
- Independent Windows PyInstaller specifications with build-time checks for
  forbidden packages and Core networking binaries; no merged executable bundle.
- Frozen-Core resource paths for bundled Alembic migrations and a mutable SQLite
  path under the platform application-data directory.
- Windows provisioning templates for a dedicated non-admin Monitor identity,
  passwordless S4U scheduled execution, protected Core/Monitor/exchange ACLs,
  and scoped firewall rules.
- Separate configurable Monitor private-data and one-way exchange directories.
- Windows post-provisioning checks for expected protected ACLs, principals,
  firewall rules, and executable targets.
- Regulatory package schema version 2 with Ed25519 domain-separated signatures,
  signed package/key identifiers and timestamps, a 48-hour default expiry, and
  a hard seven-day lifetime limit.
- Monitor-owned signing-key store with UUID identities, validity periods,
  public-key fingerprint verification, active-key selection, and restrictive
  POSIX development permissions.
- Core-owned append-only public-key trust store with overlapping rotation keys
  and irreversible revocation lifecycle.
- Authenticated Core importer with future/expiry checks, accepted and quarantine
  archives, content-hash verification, and recursive secret-field rejection.
- Database-backed replay protection and an immutable audit record for accepted,
  malformed, untrusted, revoked, expired, invalid-signature, oversized,
  symbolic-link, and replayed attempts.
- Strict initial public-key record and one-time Core trust bootstrap. Installer
  retries are idempotent only for the exact same key; attempts to appoint a
  different root are rejected.
- Domain-separated, current-key-signed rotation records with bounded lifetime,
  replay protection, immutable rotation history, and overlapping trusted keys.
- Monitor bootstrap command that generates its first private key under the
  Monitor identity and exports only the public record into the one-way exchange.
- Controlled retention of replayed and quarantined raw bytes with integrity
  verification, accepted-archive preservation, and append-only deletion,
  missing-file, failure, and tamper-block events. Enforcement runs during Core
  startup against the Core-owned regulatory archive.
- Windows trust-initialization orchestration plus real cross-identity filesystem
  probes using the configured Core identity and Monitor S4U task.
- Local Integration SDK enforcing read-only accounting/bank capabilities,
  declared datasets, source identity, stable IDs, finite amounts, timezone-aware
  capture times, and bounded cursors before analysis.
- Read-only 1C adapter shell with an injected transport, mapping profile,
  full/incremental request support, separate accounting facts and payment
  calendar, per-record rejection diagnostics, and a deterministic fixture
  transport.
- Canonical bank transaction, statement, and synchronization-batch models with
  provider IDs, value/booking dates, status, account, counterparty, and source
  provenance.
- Bounded local CSV bank adapter with configurable columns, duplicate removal,
  derived-ID diagnostics, malformed-row reporting, and symbolic-link rejection.
- Deterministic bank-to-accounting reconciliation using provider IDs first and
  unique exact-field matching second; missing, ambiguous, conflicting, stale,
  and balance-mismatch states enter the preflight report and are never guessed.
- Immutable local bank synchronization history with canonical JSON, SHA-256
  verification, cursors, and links from the accounting snapshot to the bank run.
- Additive migrations `0004` through `0007`; the prototype database is at
  `0007_integration_sdk` with its existing company and eight cash-flow records
  preserved.
- The one-click dashboard now includes a dependency-free 30-day daily-balance
  chart, a bounded list of upcoming outflows, the latest successful run time,
  and synchronized primary/stress presentation.
- The desktop UI lists the 20 latest local forecasts after restart. Opening an
  entry verifies both the analysis and source-snapshot SHA-256 hashes and reads
  the stored forecast, events, obligations, and consequences without rerunning
  the financial calculation. Failed integrity checks disable only the affected
  entry.

## Verification

Run with the project virtual environment:

```bash
.venv/bin/python -m ruff check .
.venv/bin/python -m pytest -q
```

Latest result: Ruff passed; 114 tests passed, including Ed25519 tamper rejection,
key rotation and revocation, package expiry, quarantine, replay protection,
immutable import audit, archive-integrity verification, distribution manifests
and wheel-boundary verification, the regulatory trust
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
- Windows artifact specifications, provisioning, initial-trust orchestration,
  and cross-identity filesystem probes exist but have not been executed on the
  supported Windows release VM. OS isolation is therefore prepared, not yet
  release-verified.
- Executable and installer code signing are not implemented. The bootstrap
  command path exists, but it is trustworthy only when invoked by a signed
  installer after ACL provisioning.
- Monitor private keys are protected by file permissions/ACL design, not yet by
  Windows CNG, DPAPI, or hardware-backed storage.
- The fiscal engine supports only a fictional percentage rule and is not a real
  tax implementation.
- Penalty and fine structures are generic and tested only with fictional rules;
  no real jurisdictional formula has been activated.
- No network access has been added.
- The 1C contract, mapper, and fixture transport exist, but no concrete 1C
  configuration or COM/file/local-sidecar transport has been selected.
- Bank CSV ingestion and reconciliation exist, but MT940, CAMT.053, XLSX, and
  provider-specific bank adapters are not implemented.
- Automatic bank API access is intentionally not authorized yet because it
  would handle company data while using the internet and therefore needs its own
  isolated threat model.

## Next implementation slice

1. Persist the exact rule-set provenance needed for an auditable
   "repeat on the same inputs" action; do not substitute the current scenario
   version and call it the same historical input.
2. Complete the fictional signed-package path into a non-active candidate rule
   and add a bounded internal review/diagnostic view.
3. Produce an unsigned internal portable build and execute the documented MVP
   acceptance suite on a clean Windows 11 VM. Code signing remains required
   before external distribution, not for this fictional-data acceptance build.
4. Run final first-start, restart/history, offline, frozen-resource, database
   growth, and timing checks; then refresh the factual project description.
5. Finalize private-key custody (DPAPI/CNG or an explicitly accepted ACL-only
   prototype decision) before enabling Monitor outside the local prototype.
6. Select the first target 1C configuration and implement one read-only local
   transport plus its mapping profile and golden fixture export.
7. Select the first bank statement format/provider and add its adapter with
   golden reconciliation fixtures.
8. Implement a constrained downloader that revalidates the allowlist after every
   redirect, then connect one stable official Georgian source without AI.
