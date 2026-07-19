# ADR-008: Local accounting and bank integration SDK

- Status: Accepted
- Date: 2026-07-19
- Product: FinRadar

## Context

FinRadar must be useful before a particular 1C configuration or Georgian bank
is selected. Source schemas differ, but those differences must not leak into the
forecast, fiscal engine, or UI. Bank data also need to be reconciled with
accounting facts without allowing the software to invent a match.

Company financial data remains local. The existing rule that Core contains no
internet client remains in force.

## Decision

### Integration contracts

Accounting adapters produce a versioned canonical financial snapshot. Bank
adapters produce a separate canonical bank synchronization batch. The shared
Integration SDK rejects writable connectors, mismatched source identities,
undeclared datasets, duplicate stable identifiers, non-finite amounts, naive
timestamps, and malformed cursors before analysis.

An available empty dataset remains distinct from an unavailable dataset.
Adapter-level rejected records become typed source issues and are included in
the same `ready`, `limited`, or `blocked` preflight report that controls the
forecast.

### 1C boundary

The 1C adapter depends on an injected read-only transport and a configurable
mapping profile. The current fixture transport proves the contract without a 1C
runtime. A real transport may later use a local file export, Windows COM, named
pipe, or a separately isolated local-network connector.

An OData or HTTP client is not silently added to Core. If the selected 1C
deployment requires local HTTP, it needs a separate connector process that is
blocked from the public internet, or an explicit revision of the Core network
policy.

### Bank boundary

Bank statements are normalized independently of accounting records. The first
concrete adapter reads a bounded local CSV file, rejects symbolic links, maps
provider columns through a profile, derives an identity only when the provider
does not supply one, and reports rejected and duplicate rows.

Reconciliation uses a stable bank transaction ID first. A deterministic
fallback uses date, direction, amount, currency, and account only when exactly
one accounting fact matches. Multiple candidates are `ambiguous`; a linked ID
with different values is a `conflict`; absence is
`missing_in_accounting`. FinRadar never chooses among ambiguous records.

An automatic bank API connector would necessarily have internet access while
handling company data. It is therefore not authorized by this ADR. It requires
a separate threat model and an isolated bank-specific boundary restricted to
the selected bank, or continued use of local statement import.

### Local audit

Raw normalized bank batches are stored only in the Core database as canonical
JSON with SHA-256 integrity hashes. Synchronization rows and bank snapshots are
append-only and protected by immutable SQLite triggers. The accounting snapshot
stores the linked bank run ID and source cursor so a forecast can be reproduced.

## Consequences

- A new 1C configuration supplies a transport and mapping profile instead of
  changing forecast code.
- A new statement format supplies a bank adapter while reconciliation remains
  unchanged.
- Missing recent bank coverage and operations absent from accounting are shown
  to the user before the forecast.
- No actual 1C credentials, bank credentials, public network access, or real
  customer data are introduced by this implementation slice.
- CSV is the only concrete bank file format currently implemented; MT940,
  CAMT.053, XLSX, and provider APIs remain future adapters.
