from dataclasses import dataclass
from datetime import date
from enum import Enum


class ObligationKind(str, Enum):
    CONTRACTUAL_PAYMENT = "contractual_payment"
    TAX = "tax"
    TAX_WITHHOLDING = "tax_withholding"
    PENSION_CONTRIBUTION = "pension_contribution"
    TAX_REGIME = "tax_regime"
    RELIEF = "relief"
    REFUND_OR_CREDIT = "refund_or_credit"
    FEE = "fee"
    PENALTY = "penalty"
    LATE_PAYMENT_INTEREST = "late_payment_interest"
    REPORTING_DUTY = "reporting_duty"


class ApplicabilityScope(str, Enum):
    GENERAL = "general"
    COMPANY_SPECIFIC = "company_specific"
    EMPLOYEE_SPECIFIC = "employee_specific"
    TRANSACTION_SPECIFIC = "transaction_specific"
    MUNICIPAL = "municipal"
    SECTOR_SPECIFIC = "sector_specific"
    CONSEQUENCE_ONLY = "consequence_only"


class CashFlowTreatment(str, Enum):
    CALCULATION_BASE = "calculation_base"
    DIRECT_OUTFLOW = "direct_outflow"
    WITHHELD_REMITTANCE = "withheld_remittance"
    EMPLOYER_ADDITIONAL_OUTFLOW = "employer_additional_outflow"
    POTENTIAL_INFLOW = "potential_inflow"
    MODIFIER_ONLY = "modifier_only"
    NO_COMPANY_CASH_FLOW = "no_company_cash_flow"
    CONTINGENT_OUTFLOW = "contingent_outflow"


class FormulaStatus(str, Enum):
    IMPLEMENTED = "implemented"
    PARTIALLY_IMPLEMENTED = "partially_implemented"
    CATALOG_ONLY = "catalog_only"


@dataclass(frozen=True, slots=True)
class LegalSource:
    source_id: str
    title: str
    url: str
    provisions: tuple[str, ...] = ()
    note: str = ""


@dataclass(frozen=True, slots=True)
class MandatoryObligation:
    instrument_id: str
    name_ru: str
    kind: ObligationKind
    applicability: ApplicabilityScope
    cash_flow_treatment: CashFlowTreatment
    formula_status: FormulaStatus
    payer_role: str
    recipient: str
    trigger: str
    required_data: tuple[str, ...]
    source_ids: tuple[str, ...]
    group_id: str | None = None
    parent_instrument_id: str | None = None
    calculation_rule_ids: tuple[str, ...] = ()
    rate_rule_ids: tuple[str, ...] = ()
    note: str = ""


@dataclass(frozen=True, slots=True)
class CatalogFinding:
    finding_id: str
    statement: str
    source_ids: tuple[str, ...]
    consequence: str


@dataclass(frozen=True, slots=True)
class MandatoryObligationCatalog:
    catalog_id: str
    version: int
    jurisdiction: str
    verified_on: date
    rates_included: bool
    sources: tuple[LegalSource, ...]
    entries: tuple[MandatoryObligation, ...]
    findings: tuple[CatalogFinding, ...] = ()

    def entry(self, instrument_id: str) -> MandatoryObligation:
        for item in self.entries:
            if item.instrument_id == instrument_id:
                return item
        raise LookupError(f"Unknown mandatory-obligation instrument: {instrument_id}.")

    def group(self, group_id: str) -> tuple[MandatoryObligation, ...]:
        return tuple(item for item in self.entries if item.group_id == group_id)


def validate_obligation_catalog(
    catalog: MandatoryObligationCatalog,
) -> MandatoryObligationCatalog:
    if catalog.version < 1:
        raise ValueError("Catalog version must be positive.")
    if catalog.jurisdiction != "GE":
        raise ValueError("This catalog contract currently supports Georgia only.")
    if catalog.rates_included:
        raise ValueError("The classification catalog must not contain rates.")

    source_ids = tuple(item.source_id for item in catalog.sources)
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("Catalog source identifiers must be unique.")
    entry_ids = tuple(item.instrument_id for item in catalog.entries)
    if len(entry_ids) != len(set(entry_ids)):
        raise ValueError("Catalog instrument identifiers must be unique.")
    known_sources = set(source_ids)
    known_entries = set(entry_ids)

    for item in catalog.entries:
        if not item.source_ids or not set(item.source_ids) <= known_sources:
            raise ValueError(
                f"Catalog instrument {item.instrument_id} has invalid sources."
            )
        if (
            item.parent_instrument_id is not None
            and item.parent_instrument_id not in known_entries
        ):
            raise ValueError(
                f"Catalog instrument {item.instrument_id} has an unknown parent."
            )
        if item.parent_instrument_id == item.instrument_id:
            raise ValueError("A catalog instrument cannot be its own parent.")

    for finding in catalog.findings:
        if not finding.source_ids or not set(finding.source_ids) <= known_sources:
            raise ValueError(f"Catalog finding {finding.finding_id} has invalid sources.")

    tax_ids = {
        item.instrument_id
        for item in catalog.entries
        if item.kind is ObligationKind.TAX
    }
    expected_tax_ids = {
        "ge-tax-income",
        "ge-tax-profit",
        "ge-tax-vat",
        "ge-tax-excise",
        "ge-tax-import",
        "ge-tax-property",
    }
    if tax_ids != expected_tax_ids:
        raise ValueError("The catalog must contain exactly the six Georgian taxes.")

    _validate_payroll_composition(catalog)
    return catalog


def _validate_payroll_composition(catalog: MandatoryObligationCatalog) -> None:
    payroll = {item.instrument_id: item for item in catalog.group("ge-payroll")}
    expected = {
        "ge-payroll-gross-salary",
        "ge-payroll-net-salary",
        "ge-withholding-employment-income-tax",
        "ge-pension-employee-contribution",
        "ge-pension-employer-contribution",
        "ge-pension-state-cofinancing",
        "ge-payroll-reporting",
    }
    if set(payroll) != expected:
        raise ValueError("The Georgian payroll catalog is incomplete.")
    if (
        payroll["ge-payroll-gross-salary"].cash_flow_treatment
        is not CashFlowTreatment.CALCULATION_BASE
    ):
        raise ValueError("Gross salary must be a calculation base, not a cash outflow.")
    if (
        payroll["ge-payroll-net-salary"].cash_flow_treatment
        is not CashFlowTreatment.DIRECT_OUTFLOW
    ):
        raise ValueError("Net salary must be the direct employee cash outflow.")
    if (
        payroll["ge-pension-state-cofinancing"].cash_flow_treatment
        is not CashFlowTreatment.NO_COMPANY_CASH_FLOW
    ):
        raise ValueError("State pension co-financing is not company cash flow.")
