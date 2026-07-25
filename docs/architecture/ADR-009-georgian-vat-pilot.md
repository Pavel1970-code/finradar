# ADR-009: Narrow deterministic Georgian VAT pilot

- Status: Accepted for prototype scenarios
- Date: 2026-07-25
- Product: FinRadar

## Context

The generic percentage rule cannot safely represent Georgian VAT. VAT payable
depends on several values, while a negative net position is a credit and not an
automatically dated cash receipt. Missing data must not be replaced with zero,
and the first implementation must not imply support for exemptions, mixed use,
or special operations.

The normative facts were manually verified in the Georgian-language
consolidated Tax Code published by Matsne:

- Article 166 sets the VAT rate at 18 percent.
- Article 167 defines the reporting period as a calendar month.
- Article 168 requires the return and payment no later than the fifteenth day of
  the following month.
- Article 3 moves a deadline falling on a non-business day to the next business
  day.
- Article 181 establishes a right to a refund when deductible VAT exceeds
  chargeable VAT.
- Articles 177 and 178 contain proportional-deduction and restriction rules,
  which are outside this pilot.

Official source used for rule version 1:
[Tax Code of Georgia, consolidation 245 (Georgian PDF)](https://matsne.gov.ge/ka/document/download/1043717/245/ge/pdf).

## Decision

Core has a separate versioned `GeorgianVatRule`. It is activated in the bundled
pilot only for a fictional company whose explicit tax-regime marker limits the
calculation to registered, standard-rate domestic operations.

The rule requires one value for every component in the same calendar month and
company currency:

1. standard-rate taxable turnover excluding VAT;
2. deductible input VAT already validated by accounting;
3. additional output-VAT adjustments;
4. import VAT payable;
5. reverse-charge VAT payable;
6. exempt or mixed-use turnover scope control;
7. special-transaction amount scope control.

The final payable is:

```text
turnover × 18%
+ output adjustments
+ import VAT
+ reverse-charge VAT
− deductible input VAT
```

All component amounts are normalized to currency precision. A positive result
creates a stable fiscal obligation and is reconciled with the existing payment
calendar. A zero result creates no payment. A negative result is retained as a
credit position but is not added as a forecast inflow because neither refund
approval nor payment date is known.

The calculator returns `unresolved` when:

- a component is missing or duplicated;
- component periods or currencies do not agree;
- a component that must be non-negative is negative;
- the reporting interval is not a calendar month;
- either scope-control metric is non-zero.

The due date is the fifteenth day of the following month. Weekends and
rule-supplied non-business dates are rolled forward. The bundled June 2026
scenario is due on Wednesday, 15 July 2026, so it does not depend on an
incomplete holiday calendar.

## Consequences and limits

- The pilot uses real manually verified normative values with fictional company
  data. It is not a complete tax opinion or production tax calculator.
- AI is not involved in the formula, applicability result, reconciliation, or
  cash forecast.
- The real source is not downloaded automatically. Amendment detection and the
  signed candidate-review-activation path remain separate future work.
- Input-tax eligibility, exemptions, proportional deductions, corrections,
  special transactions, foreign-currency rules, and refund timing require
  additional reviewed rule types and fixtures.
- A maintained Georgian business-day calendar is required before general date
  calculation can be considered production-ready.
