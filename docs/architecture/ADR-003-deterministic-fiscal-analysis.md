# ADR-003: Deterministic fiscal applicability and calculation

- Status: Accepted
- Date: 2026-07-19
- Product: FinRadar

## Context

FinRadar must combine current accounting information, a payment calendar, and
verified fiscal rules without allowing AI output to determine financial amounts.
It must also report when a rule cannot be evaluated because required accounting
or company attributes are missing.

## Decision

Fiscal analysis is a deterministic pipeline:

1. An active, versioned rule is matched to company jurisdiction, tax regime, and
   its effective period.
2. The calculation engine selects an explicitly named accounting metric.
3. The rule formula creates a fiscal obligation with a stable identity based on
   rule identity and accounting period. Rule version remains audit metadata and
   does not create a duplicate obligation.
4. Reconciliation matches that identity against payment-calendar and settled
   accounting events.
5. Only the unpaid amount enters the unified cash forecast.

Applicability returns `applied`, `not_applicable`, or `unresolved`. Missing data
always produces `unresolved`; the engine does not infer or invent values.

AI-extracted rules remain candidates until a separate validation and activation
process promotes them to active rules. Candidate, validated, reviewed,
superseded, and inactive rules never affect calculations.

## Initial scope

The first implementation supports a fictional percentage rule over one named
accounting metric and a deterministic number of days after the metric period.
It deliberately does not claim to implement any real tax, penalty, benefit, or
jurisdiction.

## Consequences

- Identical inputs and rule versions produce identical obligations.
- Existing, settled, partially paid, cancelled, and duplicate calendar records
  have explicit reconciliation behavior.
- Rule extraction, legal review, formula execution, and human explanation remain
  separate responsibilities.
- Real fiscal formulas require additional reviewed rule types and golden tests.

