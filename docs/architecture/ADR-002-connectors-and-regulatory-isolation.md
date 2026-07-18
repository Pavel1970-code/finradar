# ADR-002: Accounting connectors and regulatory network isolation

- Status: Accepted
- Date: 2026-07-18
- Product: FinRadar

## Context

FinRadar must analyse accounting facts and the payment calendar already held in
an accounting system such as 1C. Users should not have to reproduce these data
manually in FinRadar.

FinRadar must also monitor public fiscal sources. This requires internet access,
while customer financial data must remain on customer-controlled infrastructure.

## Decision

Accounting systems are accessed through read-only connector adapters. Every
adapter maps source-specific records to a canonical financial snapshot before
the calculation engine sees them.

The canonical snapshot records both the extracted records and which datasets
the source successfully supplied. An empty supplied dataset is different from
an unavailable dataset. A preflight service reports missing, stale, invalid, or
unsupported information before a forecast is presented.

External network access is limited to a regulatory-monitoring boundary. That
boundary may retrieve public documents from an explicit allowlist, but it must
not read the accounting database or canonical financial snapshots.

AI may extract candidate facts from public regulatory documents and explain
verified results. AI output does not activate fiscal rules, decide their
applicability, or calculate financial amounts. Only versioned active rules and
deterministic code participate in calculations.

## Consequences

- Domain and forecast code are independent of 1C, CSV, and other source formats.
- Connector capabilities and synchronization outcomes are explicit.
- Forecast readiness can be blocked or limited with auditable reasons.
- A connector can be developed before a particular 1C configuration is chosen.
- Network policy tests must prohibit network clients everywhere except the
  isolated regulatory-monitoring infrastructure package.
- Regulatory documents, extracted candidates, reviewed rules, and active rules
  require separate lifecycle states.

