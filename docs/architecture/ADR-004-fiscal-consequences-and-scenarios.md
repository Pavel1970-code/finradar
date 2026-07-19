# ADR-004: Fiscal consequences and forecast scenarios

- Status: Accepted
- Date: 2026-07-19
- Product: FinRadar

## Context

Late or incomplete fiscal payments may create penalties and fines. Some charges
already exist in accounting records, some can be calculated after an actual
violation, and others are only potential future exposure. Treating all three as
ordinary confirmed payments would overstate liabilities and hide uncertainty.

## Decision

FinRadar distinguishes four consequence states:

- `accrued`: supplied by the accounting source;
- `calculated`: a confirmed violation and active deterministic rule provide all
  inputs required for calculation;
- `contingent`: a future or legally conditional exposure;
- `unresolved`: the calculation is missing a rate, formula, decision, or another
  required input.

Accrued and calculated amounts enter the primary forecast. Contingent amounts
enter only a separately labelled stress forecast. Unresolved consequences never
enter either forecast as invented amounts.

Late-payment penalties are calculated over inclusive daily segments. Each
segment records its rate, effective dates, number of days, amount, and source.
Missing, overlapping, or invalid rate coverage produces `unresolved` rather than
a partial total.

Formalized fines may use either a fixed amount or a percentage of outstanding
principal, with optional minimum and maximum limits. A fine that requires an
authority decision remains contingent until the decision identifier is present.
Fine rules explicitly identify the obligation rule families to which they apply.

Accounting events may carry a fiscal consequence identity and a link to their
original obligation. This lets reconciliation recognize an already accrued
charge and avoid generating it a second time.

## Consequences

- The primary liquidity forecast does not silently include hypothetical fines.
- A stress forecast can demonstrate how continued arrears worsen a cash gap.
- Changes in daily penalty rates are auditable by segment.
- Real legal rules still require a verified source, active version, applicability
  conditions, and jurisdiction-specific golden tests before activation.

