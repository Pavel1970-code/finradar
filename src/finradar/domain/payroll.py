from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum


class PayrollRecordStatus(str, Enum):
    DRAFT = "draft"
    ACCRUED = "accrued"
    APPROVED = "approved"
    PARTIALLY_PAID = "partially_paid"
    PAID = "paid"
    CANCELLED = "cancelled"


class PayrollTaxTreatment(str, Enum):
    STANDARD = "standard"
    SOURCE_REPORTED_EXCEPTION = "source_reported_exception"
    UNKNOWN = "unknown"


class PayrollPaymentForm(str, Enum):
    CASH = "cash"
    NON_CASH = "non_cash"
    MIXED = "mixed"


class PensionParticipationStatus(str, Enum):
    PARTICIPANT = "participant"
    NOT_PARTICIPANT = "not_participant"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class PayrollRecord:
    """Canonical local payroll row independent of a particular accounting product.

    The record intentionally contains no employee name or national identifier.
    ``employee_local_id`` is a stable local/pseudonymous key supplied by the
    accounting connector.
    """

    external_id: str
    payroll_run_id: str
    employee_local_id: str
    period_start: date
    period_end: date
    payment_date: date
    currency: str
    status: PayrollRecordStatus
    payment_form: PayrollPaymentForm
    gross_cash_compensation: Decimal
    taxable_non_cash_benefit: Decimal
    income_tax_base: Decimal
    income_tax_withheld: Decimal
    pension_contribution_base: Decimal
    employee_pension_contribution: Decimal
    employer_pension_contribution: Decimal
    other_employee_withholdings: Decimal
    net_salary_payable: Decimal
    employer_other_costs: Decimal
    pension_participation: PensionParticipationStatus
    tax_treatment: PayrollTaxTreatment
    income_tax_remittance_due_date: date
    payroll_declaration_due_date: date
    pension_contribution_due_date: date
    state_pension_cofinancing: Decimal | None = None
    annual_pension_base_before: Decimal | None = None
    tax_treatment_reference: str = ""
    source_reference: str = ""

    def __post_init__(self) -> None:
        for label, value, maximum in (
            ("external_id", self.external_id, 200),
            ("payroll_run_id", self.payroll_run_id, 200),
            ("employee_local_id", self.employee_local_id, 200),
        ):
            if not value.strip() or len(value.strip()) > maximum:
                raise ValueError(f"Payroll {label} is invalid.")
        if self.period_end < self.period_start:
            raise ValueError("Payroll period is inverted.")
        if len(self.currency) != 3 or self.currency != self.currency.upper():
            raise ValueError("Payroll currency must be an uppercase ISO-style code.")
        for label, amount in self.amounts().items():
            if not amount.is_finite() or amount < Decimal("0"):
                raise ValueError(f"Payroll amount {label} must be finite and non-negative.")
        if (
            self.state_pension_cofinancing is not None
            and (
                not self.state_pension_cofinancing.is_finite()
                or self.state_pension_cofinancing < Decimal("0")
            )
        ):
            raise ValueError(
                "State pension co-financing must be finite and non-negative."
            )
        if (
            self.annual_pension_base_before is not None
            and (
                not self.annual_pension_base_before.is_finite()
                or self.annual_pension_base_before < Decimal("0")
            )
        ):
            raise ValueError(
                "Annual pension base before the payroll row must be non-negative."
            )

    def amounts(self) -> dict[str, Decimal]:
        return {
            "gross_cash_compensation": self.gross_cash_compensation,
            "taxable_non_cash_benefit": self.taxable_non_cash_benefit,
            "income_tax_base": self.income_tax_base,
            "income_tax_withheld": self.income_tax_withheld,
            "pension_contribution_base": self.pension_contribution_base,
            "employee_pension_contribution": self.employee_pension_contribution,
            "employer_pension_contribution": self.employer_pension_contribution,
            "other_employee_withholdings": self.other_employee_withholdings,
            "net_salary_payable": self.net_salary_payable,
            "employer_other_costs": self.employer_other_costs,
        }

    @property
    def employee_deductions(self) -> Decimal:
        return (
            self.income_tax_withheld
            + self.employee_pension_contribution
            + self.other_employee_withholdings
        )

    @property
    def pension_remittance_payable(self) -> Decimal:
        return (
            self.employee_pension_contribution
            + self.employer_pension_contribution
        )

    @property
    def employer_total_cost(self) -> Decimal:
        return (
            self.gross_cash_compensation
            + self.employer_pension_contribution
            + self.employer_other_costs
        )

    @property
    def company_cash_outflow(self) -> Decimal:
        """Total recipient cash flows; gross salary itself is not added again."""

        return (
            self.net_salary_payable
            + self.income_tax_withheld
            + self.pension_remittance_payable
            + self.other_employee_withholdings
            + self.employer_other_costs
        )
