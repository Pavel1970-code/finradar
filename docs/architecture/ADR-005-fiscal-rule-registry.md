# ADR-005: Immutable fiscal rule versions and lifecycle events

- Status: Accepted
- Date: 2026-07-19
- Product: FinRadar

## Context

Regulatory monitoring and AI-assisted extraction will produce candidate rules.
Those candidates must not affect financial calculations until they have passed
technical validation and human review. Editing a rule in place would destroy the
audit trail for earlier forecasts.

## Decision

The content of every fiscal rule version is stored as canonical JSON with a
SHA-256 hash. The definition is immutable and uniquely identified by `rule_id`
and `version`.

Lifecycle state is stored as a separate append-only event sequence:

```text
candidate -> validated -> reviewed -> active -> superseded
```

Skipping a state or registering a new rule directly as active is prohibited.
Activating a newer version atomically appends `superseded` to another active
version of the same rule identity.

Only versions whose latest lifecycle event is `active` are loaded into the
analytical pipeline. Obligation, late-payment penalty, and fine rules are grouped
into a typed active rule set before analysis.

Every fiscal analysis result is stored as immutable canonical JSON linked to its
synchronization run when available. It includes primary and stress forecasts,
rule applicability, reconciliation, generated consequences, algorithm version,
analysis date, and horizon. A SHA-256 hash is verified when history is read.

## Consequences

- AI extraction can safely populate candidates without changing calculations.
- Historical forecasts retain the exact rule version and analytical result used.
- Corrections create new versions instead of rewriting regulatory history.
- A future UI must expose lifecycle reasons and clearly separate candidates from
  active rules.

