from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from importlib import resources
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from finradar.application.fiscal_rules import ActiveFiscalRuleSet
from finradar.domain.banking import (
    BankStatement,
    BankSynchronizationBatch,
    BankTransaction,
    BankTransactionDirection,
    BankTransactionStatus,
)
from finradar.domain.financial_snapshot import (
    AccountBalance,
    AccountingMetric,
    CompanyProfile,
    CounterpartyKind,
    CounterpartyReference,
    DatasetKind,
    FinancialDirection,
    FinancialEvent,
    FinancialEventKind,
    FinancialEventStatus,
    FinancialSnapshot,
    PaymentBasis,
    SourceDataIssue,
    SourceIssueSeverity,
)
from finradar.domain.fiscal import (
    FiscalRuleStatus,
    GeorgianVatRule,
    PercentageFiscalRule,
)
from finradar.domain.fiscal_consequences import (
    FineRule,
    LatePaymentPenaltyRule,
    PenaltyRatePeriod,
    ViolationEvent,
    ViolationType,
)


SCENARIO_SCHEMA_VERSION = 1
SCENARIO_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class DemoScenarioError(ValueError):
    """Raised when a bundled scenario fails its contract or integrity check."""


class _ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _CompanyData(_ContractModel):
    external_id: str
    name: str
    base_currency: str
    jurisdiction: str | None = None
    tax_regime: str | None = None


class _BalanceData(_ContractModel):
    external_id: str
    name: str
    currency: str
    amount: Decimal
    balance_date: date


class _MetricData(_ContractModel):
    code: str
    amount: Decimal
    currency: str
    period_start: date
    period_end: date
    source_reference: str = ""


class _CounterpartyData(_ContractModel):
    external_id: str
    name: str
    kind: CounterpartyKind


class _PaymentBasisData(_ContractModel):
    document_type: str
    document_number: str
    document_date: date
    description: str = ""


class _EventData(_ContractModel):
    external_id: str
    title: str
    amount: Decimal
    currency: str
    due_date: date
    direction: FinancialDirection
    kind: FinancialEventKind
    status: FinancialEventStatus = FinancialEventStatus.PLANNED
    settled_amount: Decimal = Decimal("0.00")
    obligation_key: str | None = None
    related_obligation_key: str | None = None
    fiscal_consequence_type: str | None = None
    category: str | None = None
    account_external_id: str | None = None
    source_reference: str = ""
    bank_transaction_id: str | None = None
    counterparty: _CounterpartyData | None = None
    payment_purpose: str = ""
    payment_basis: _PaymentBasisData | None = None
    period_start: date | None = None
    period_end: date | None = None


class _IssueData(_ContractModel):
    code: str
    severity: SourceIssueSeverity
    dataset: DatasetKind
    message: str
    impact: str
    source_reference: str = ""


class _AccountingData(_ContractModel):
    source_system: str
    captured_at: datetime
    available_datasets: frozenset[DatasetKind]
    company: _CompanyData | None
    balances: tuple[_BalanceData, ...] = ()
    metrics: tuple[_MetricData, ...] = ()
    events: tuple[_EventData, ...] = ()
    source_issues: tuple[_IssueData, ...] = ()
    source_cursor: str | None = None


class _BankTransactionData(_ContractModel):
    external_id: str
    account_external_id: str
    booking_date: date
    value_date: date
    direction: BankTransactionDirection
    amount: Decimal
    currency: str
    description: str
    reference: str = ""
    status: BankTransactionStatus = BankTransactionStatus.BOOKED
    counterparty_name: str = ""
    counterparty_account: str = ""
    source_reference: str = ""


class _BankStatementData(_ContractModel):
    statement_id: str
    account_external_id: str
    period_start: date
    period_end: date
    opening_balance: Decimal | None
    closing_balance: Decimal | None
    transactions: tuple[_BankTransactionData, ...]


class _BankData(_ContractModel):
    source_system: str
    captured_at: datetime
    available: bool
    statements: tuple[_BankStatementData, ...] = ()
    source_issues: tuple[_IssueData, ...] = ()
    next_cursor: str | None = None


class _FiscalRuleData(_ContractModel):
    rule_id: str
    version: int = Field(ge=1)
    title: str
    jurisdiction: str
    tax_regimes: frozenset[str]
    effective_from: date
    effective_to: date | None = None
    base_metric_code: str
    rate: Decimal
    payment_days_after_period_end: int = Field(ge=0)
    obligation_category: str
    source_reference: str
    payment_recipient: _CounterpartyData | None = None


class _GeorgianVatRuleData(_ContractModel):
    rule_id: str
    version: int = Field(ge=1)
    title: str
    jurisdiction: str
    tax_regimes: frozenset[str]
    effective_from: date
    effective_to: date | None = None
    taxable_turnover_metric_code: str
    deductible_input_vat_metric_code: str
    output_adjustment_metric_code: str
    import_vat_metric_code: str
    reverse_charge_vat_metric_code: str
    excluded_or_mixed_use_metric_code: str
    special_transaction_metric_code: str
    rate: Decimal
    due_day_of_following_month: int = Field(ge=1, le=28)
    obligation_category: str
    source_reference: str
    payment_recipient: _CounterpartyData | None = None
    non_business_dates: frozenset[date] = frozenset()


_ObligationRuleData = _FiscalRuleData | _GeorgianVatRuleData


class _PenaltyPeriodData(_ContractModel):
    effective_from: date
    effective_to: date | None = None
    daily_rate: Decimal


class _PenaltyRuleData(_ContractModel):
    rule_id: str
    version: int = Field(ge=1)
    applies_to_obligation_rule_id: str
    grace_days: int = Field(ge=0)
    rate_periods: tuple[_PenaltyPeriodData, ...]
    source_reference: str


class _FineRuleData(_ContractModel):
    rule_id: str
    version: int = Field(ge=1)
    violation_type: ViolationType
    applies_to_obligation_rule_ids: frozenset[str]
    fixed_amount: Decimal | None = None
    percentage_of_outstanding: Decimal | None = None
    minimum_amount: Decimal | None = None
    maximum_amount: Decimal | None = None
    requires_authority_decision: bool
    source_reference: str


class _ViolationData(_ContractModel):
    violation_id: str
    violation_type: ViolationType
    obligation_key: str
    occurred_on: date
    confirmed: bool
    authority_decision_id: str | None = None


class DemoGoldenResult(_ContractModel):
    readiness_status: str
    opening_balance: Decimal
    closing_balance: Decimal
    minimum_balance: Decimal
    first_gap_date: date | None
    required_funding: Decimal
    fiscal_obligation_amount: Decimal
    stress_minimum_balance: Decimal
    issue_codes: tuple[str, ...] = ()
    bank_matched_count: int = Field(default=0, ge=0)
    bank_missing_count: int = Field(default=0, ge=0)
    calculated_penalty_amount: Decimal = Decimal("0.00")
    contingent_fine_amount: Decimal = Decimal("0.00")
    comparison: DemoGoldenComparison | None = None


class DemoGoldenComparison(_ContractModel):
    baseline_rate: Decimal
    current_rate: Decimal
    baseline_obligation_amount: Decimal
    current_obligation_amount: Decimal
    baseline_minimum_balance: Decimal
    current_minimum_balance: Decimal
    baseline_first_gap_date: date | None
    current_first_gap_date: date | None
    baseline_required_funding: Decimal
    current_required_funding: Decimal
    obligation_delta: Decimal
    minimum_balance_delta: Decimal
    required_funding_delta: Decimal


class _ScenarioPayload(_ContractModel):
    title: str
    fictional_notice: str
    as_of: date
    horizon_days: int = Field(ge=1, le=366)
    stress_overdue_days: int = Field(ge=0, le=366)
    accounting: _AccountingData
    bank: _BankData | None = None
    fiscal_rules: tuple[_ObligationRuleData, ...] = ()
    penalty_rules: tuple[_PenaltyRuleData, ...] = ()
    fine_rules: tuple[_FineRuleData, ...] = ()
    baseline_fiscal_rules: tuple[_ObligationRuleData, ...] = ()
    baseline_penalty_rules: tuple[_PenaltyRuleData, ...] = ()
    baseline_fine_rules: tuple[_FineRuleData, ...] = ()
    violation_events: tuple[_ViolationData, ...] = ()
    expected: DemoGoldenResult


class _ScenarioEnvelope(_ContractModel):
    schema_version: int
    scenario_id: str
    scenario_version: int = Field(ge=1)
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    payload: _ScenarioPayload


@dataclass(frozen=True, slots=True)
class DemoScenario:
    scenario_id: str
    version: int
    title: str
    fictional_notice: str
    as_of: date
    horizon_days: int
    stress_overdue_days: int
    accounting_snapshot: FinancialSnapshot
    bank_batch: BankSynchronizationBatch | None
    fiscal_rules: ActiveFiscalRuleSet
    baseline_fiscal_rules: ActiveFiscalRuleSet | None
    violation_events: tuple[ViolationEvent, ...]
    expected: DemoGoldenResult


class DemoScenarioRepository:
    """Loads immutable, checksummed scenarios from package resources or a test directory."""

    def __init__(self, resource_directory: Path | None = None) -> None:
        self._resource_directory = resource_directory

    def load(self, scenario_id: str) -> DemoScenario:
        if SCENARIO_ID_PATTERN.fullmatch(scenario_id) is None:
            raise DemoScenarioError("Demo scenario identifier is invalid.")
        try:
            content = self._read_text(f"{scenario_id}.json")
        except FileNotFoundError as error:
            raise DemoScenarioError(f"Unknown demo scenario: {scenario_id}.") from error
        try:
            raw = json.loads(content)
            envelope = _ScenarioEnvelope.model_validate(raw)
        except (json.JSONDecodeError, TypeError, ValueError) as error:
            raise DemoScenarioError("Demo scenario contract is invalid.") from error
        if envelope.schema_version != SCENARIO_SCHEMA_VERSION:
            raise DemoScenarioError("Unsupported demo scenario schema version.")
        if envelope.scenario_id != scenario_id:
            raise DemoScenarioError("Demo scenario identity does not match its filename.")
        actual_hash = _payload_hash(raw.get("payload"))
        if actual_hash != envelope.payload_sha256:
            raise DemoScenarioError("Demo scenario integrity check failed.")
        return _to_domain(envelope)

    def list(self) -> tuple[DemoScenario, ...]:
        if self._resource_directory is not None:
            scenario_ids = tuple(
                sorted(path.stem for path in self._resource_directory.glob("*.json"))
            )
        else:
            scenario_files = resources.files("finradar.demo.scenarios")
            scenario_ids = tuple(
                sorted(
                    item.name.removesuffix(".json")
                    for item in scenario_files.iterdir()
                    if item.name.endswith(".json")
                )
            )
        return tuple(self.load(scenario_id) for scenario_id in scenario_ids)

    def _read_text(self, filename: str) -> str:
        if self._resource_directory is not None:
            return (self._resource_directory / filename).read_text(encoding="utf-8")
        scenario_files = resources.files("finradar.demo.scenarios")
        return scenario_files.joinpath(filename).read_text(encoding="utf-8")


def _payload_hash(payload: object) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _to_domain(envelope: _ScenarioEnvelope) -> DemoScenario:
    payload = envelope.payload
    accounting = payload.accounting
    snapshot = FinancialSnapshot(
        source_system=accounting.source_system,
        captured_at=accounting.captured_at,
        available_datasets=accounting.available_datasets,
        company=(
            CompanyProfile(**accounting.company.model_dump())
            if accounting.company is not None
            else None
        ),
        balances=tuple(AccountBalance(**item.model_dump()) for item in accounting.balances),
        metrics=tuple(AccountingMetric(**item.model_dump()) for item in accounting.metrics),
        events=tuple(_event_to_domain(item) for item in accounting.events),
        source_issues=tuple(
            SourceDataIssue(**item.model_dump()) for item in accounting.source_issues
        ),
        source_cursor=accounting.source_cursor,
    )
    bank = payload.bank
    bank_batch = None
    if bank is not None:
        bank_batch = BankSynchronizationBatch(
            source_system=bank.source_system,
            captured_at=bank.captured_at,
            available=bank.available,
            statements=tuple(
                BankStatement(
                    statement_id=statement.statement_id,
                    account_external_id=statement.account_external_id,
                    period_start=statement.period_start,
                    period_end=statement.period_end,
                    opening_balance=statement.opening_balance,
                    closing_balance=statement.closing_balance,
                    transactions=tuple(
                        BankTransaction(**transaction.model_dump())
                        for transaction in statement.transactions
                    ),
                )
                for statement in bank.statements
            ),
            source_issues=tuple(
                SourceDataIssue(**item.model_dump()) for item in bank.source_issues
            ),
            next_cursor=bank.next_cursor,
        )
    rule_set = _to_rule_set(
        payload.fiscal_rules,
        payload.penalty_rules,
        payload.fine_rules,
    )
    baseline_rule_set = None
    if (
        payload.baseline_fiscal_rules
        or payload.baseline_penalty_rules
        or payload.baseline_fine_rules
    ):
        baseline_rule_set = _to_rule_set(
            payload.baseline_fiscal_rules,
            payload.baseline_penalty_rules,
            payload.baseline_fine_rules,
        )
    violations = tuple(
        ViolationEvent(**item.model_dump()) for item in payload.violation_events
    )
    return DemoScenario(
        scenario_id=envelope.scenario_id,
        version=envelope.scenario_version,
        title=payload.title,
        fictional_notice=payload.fictional_notice,
        as_of=payload.as_of,
        horizon_days=payload.horizon_days,
        stress_overdue_days=payload.stress_overdue_days,
        accounting_snapshot=snapshot,
        bank_batch=bank_batch,
        fiscal_rules=rule_set,
        baseline_fiscal_rules=baseline_rule_set,
        violation_events=violations,
        expected=payload.expected,
    )


def _to_rule_set(
    fiscal_rules: tuple[_ObligationRuleData, ...],
    penalty_rules: tuple[_PenaltyRuleData, ...],
    fine_rules: tuple[_FineRuleData, ...],
) -> ActiveFiscalRuleSet:
    return ActiveFiscalRuleSet(
        obligation_rules=tuple(
            _obligation_rule_to_domain(item)
            for item in fiscal_rules
        ),
        penalty_rules=tuple(
            LatePaymentPenaltyRule(
                rule_id=item.rule_id,
                version=item.version,
                applies_to_obligation_rule_id=item.applies_to_obligation_rule_id,
                grace_days=item.grace_days,
                rate_periods=tuple(
                    PenaltyRatePeriod(**period.model_dump())
                    for period in item.rate_periods
                ),
                source_reference=item.source_reference,
                status=FiscalRuleStatus.ACTIVE,
            )
            for item in penalty_rules
        ),
        fine_rules=tuple(
            FineRule(
                **item.model_dump(),
                status=FiscalRuleStatus.ACTIVE,
            )
            for item in fine_rules
        ),
    )


def _obligation_rule_to_domain(
    item: _ObligationRuleData,
) -> PercentageFiscalRule | GeorgianVatRule:
    values = item.model_dump(exclude={"payment_recipient"})
    recipient = (
        CounterpartyReference(**item.payment_recipient.model_dump())
        if item.payment_recipient is not None
        else None
    )
    rule_type = GeorgianVatRule if isinstance(item, _GeorgianVatRuleData) else PercentageFiscalRule
    return rule_type(
        **values,
        payment_recipient=recipient,
        status=FiscalRuleStatus.ACTIVE,
    )


def _event_to_domain(item: _EventData) -> FinancialEvent:
    values = item.model_dump(exclude={"counterparty", "payment_basis"})
    return FinancialEvent(
        **values,
        counterparty=(
            CounterpartyReference(**item.counterparty.model_dump())
            if item.counterparty is not None
            else None
        ),
        payment_basis=(
            PaymentBasis(**item.payment_basis.model_dump())
            if item.payment_basis is not None
            else None
        ),
    )
