from dataclasses import dataclass
from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal
from enum import Enum
from typing import TypeAlias

from finradar.domain.financial_snapshot import (
    AccountingMetric,
    CounterpartyReference,
    FinancialEvent,
    FinancialEventStatus,
    FinancialSnapshot,
)
from finradar.domain.forecast import normalize_money


class FiscalRuleStatus(str, Enum):
    CANDIDATE = "candidate"
    VALIDATED = "validated"
    REVIEWED = "reviewed"
    ACTIVE = "active"
    SUPERSEDED = "superseded"


class ApplicabilityStatus(str, Enum):
    APPLIED = "applied"
    NOT_APPLICABLE = "not_applicable"
    UNRESOLVED = "unresolved"


class ReconciliationAction(str, Enum):
    ADD_OBLIGATION = "add_obligation"
    USE_EXISTING = "use_existing"
    ALREADY_SETTLED = "already_settled"


class FiscalPositionType(str, Enum):
    PAYABLE = "payable"
    CREDIT = "credit"
    ZERO = "zero"


@dataclass(frozen=True, slots=True)
class PercentageFiscalRule:
    rule_id: str
    version: int
    title: str
    jurisdiction: str
    tax_regimes: frozenset[str]
    effective_from: date
    effective_to: date | None
    base_metric_code: str
    rate: Decimal
    payment_days_after_period_end: int
    obligation_category: str
    source_reference: str
    payment_recipient: CounterpartyReference | None = None
    status: FiscalRuleStatus = FiscalRuleStatus.CANDIDATE


@dataclass(frozen=True, slots=True)
class GeorgianVatRule:
    """Narrow deterministic VAT rule for a standard Georgian domestic taxpayer.

    The rule deliberately requires explicit zero-valued scope metrics. This prevents
    mixed-use, exempt, or otherwise special transactions from being silently treated
    as ordinary standard-rate supplies.
    """

    rule_id: str
    version: int
    title: str
    jurisdiction: str
    tax_regimes: frozenset[str]
    effective_from: date
    effective_to: date | None
    taxable_turnover_metric_code: str
    deductible_input_vat_metric_code: str
    output_adjustment_metric_code: str
    import_vat_metric_code: str
    reverse_charge_vat_metric_code: str
    excluded_or_mixed_use_metric_code: str
    special_transaction_metric_code: str
    rate: Decimal
    due_day_of_following_month: int
    obligation_category: str
    source_reference: str
    payment_recipient: CounterpartyReference | None = None
    non_business_dates: frozenset[date] = frozenset()
    status: FiscalRuleStatus = FiscalRuleStatus.CANDIDATE


FiscalObligationRule: TypeAlias = PercentageFiscalRule | GeorgianVatRule


@dataclass(frozen=True, slots=True)
class ApplicabilityResult:
    status: ApplicabilityStatus
    reasons: tuple[str, ...]
    missing_fields: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FiscalObligation:
    obligation_key: str
    rule_id: str
    rule_version: int
    title: str
    amount: Decimal
    currency: str
    due_date: date
    category: str
    base_amount: Decimal
    rate: Decimal
    source_reference: str
    explanation: str
    period_start: date | None = None
    period_end: date | None = None
    payment_recipient: CounterpartyReference | None = None


@dataclass(frozen=True, slots=True)
class FiscalCalculationComponent:
    code: str
    title: str
    amount: Decimal
    currency: str


@dataclass(frozen=True, slots=True)
class FiscalCalculationResult:
    applicability: ApplicabilityResult
    obligation: FiscalObligation | None
    rule_id: str = ""
    title: str = ""
    source_reference: str = ""
    position: FiscalPositionType | None = None
    net_amount: Decimal | None = None
    currency: str = ""
    components: tuple[FiscalCalculationComponent, ...] = ()
    explanation: str = ""


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    action: ReconciliationAction
    obligation: FiscalObligation
    matching_event_ids: tuple[str, ...]
    outstanding_amount: Decimal
    forecast_due_date: date


def assess_rule_applicability(
    rule: FiscalObligationRule,
    snapshot: FinancialSnapshot,
    *,
    as_of: date,
) -> ApplicabilityResult:
    if rule.status is not FiscalRuleStatus.ACTIVE:
        return ApplicabilityResult(
            status=ApplicabilityStatus.NOT_APPLICABLE,
            reasons=("The rule is not active.",),
        )

    if as_of < rule.effective_from or (
        rule.effective_to is not None and as_of > rule.effective_to
    ):
        return ApplicabilityResult(
            status=ApplicabilityStatus.NOT_APPLICABLE,
            reasons=("The rule is not effective on the analysis date.",),
        )

    if snapshot.company is None:
        return ApplicabilityResult(
            status=ApplicabilityStatus.UNRESOLVED,
            reasons=("Company profile is missing.",),
            missing_fields=("company_profile",),
        )

    missing_fields: list[str] = []
    if snapshot.company.jurisdiction is None:
        missing_fields.append("company.jurisdiction")
    if snapshot.company.tax_regime is None:
        missing_fields.append("company.tax_regime")
    if missing_fields:
        return ApplicabilityResult(
            status=ApplicabilityStatus.UNRESOLVED,
            reasons=("Company attributes required by the rule are missing.",),
            missing_fields=tuple(missing_fields),
        )

    if snapshot.company.jurisdiction != rule.jurisdiction:
        return ApplicabilityResult(
            status=ApplicabilityStatus.NOT_APPLICABLE,
            reasons=("Company jurisdiction does not match the rule.",),
        )
    if snapshot.company.tax_regime not in rule.tax_regimes:
        return ApplicabilityResult(
            status=ApplicabilityStatus.NOT_APPLICABLE,
            reasons=("Company tax regime does not match the rule.",),
        )

    return ApplicabilityResult(
        status=ApplicabilityStatus.APPLIED,
        reasons=("The active rule matches company jurisdiction and tax regime.",),
    )


def calculate_fiscal_obligation(
    rule: FiscalObligationRule,
    snapshot: FinancialSnapshot,
    *,
    as_of: date,
) -> FiscalCalculationResult:
    if isinstance(rule, GeorgianVatRule):
        return _calculate_georgian_vat(rule, snapshot, as_of=as_of)

    applicability = assess_rule_applicability(rule, snapshot, as_of=as_of)
    if applicability.status is not ApplicabilityStatus.APPLIED:
        return _empty_calculation(rule, applicability)

    metric = _latest_metric(snapshot.metrics, rule.base_metric_code, as_of)
    if metric is None:
        return _empty_calculation(
            rule,
            ApplicabilityResult(
                status=ApplicabilityStatus.UNRESOLVED,
                reasons=("The accounting metric required for calculation is missing.",),
                missing_fields=(f"accounting_metric:{rule.base_metric_code}",),
            ),
        )

    assert snapshot.company is not None
    if metric.currency != snapshot.company.base_currency:
        return _empty_calculation(
            rule,
            ApplicabilityResult(
                status=ApplicabilityStatus.UNRESOLVED,
                reasons=("The accounting metric currency differs from company currency.",),
                missing_fields=("currency_conversion_policy",),
            ),
        )
    if metric.amount < Decimal("0.00"):
        return _empty_calculation(
            rule,
            ApplicabilityResult(
                status=ApplicabilityStatus.UNRESOLVED,
                reasons=("A percentage obligation cannot use a negative tax base.",),
                missing_fields=(f"valid_metric:{rule.base_metric_code}",),
            ),
        )

    amount = normalize_money(metric.amount * rule.rate)
    obligation_key = (
        f"{rule.rule_id}:{metric.period_start.isoformat()}:{metric.period_end.isoformat()}"
    )
    obligation = FiscalObligation(
        obligation_key=obligation_key,
        rule_id=rule.rule_id,
        rule_version=rule.version,
        title=rule.title,
        amount=amount,
        currency=metric.currency,
        due_date=metric.period_end + timedelta(days=rule.payment_days_after_period_end),
        category=rule.obligation_category,
        base_amount=normalize_money(metric.amount),
        rate=rule.rate,
        source_reference=rule.source_reference,
        explanation=(
            f"{normalize_money(metric.amount)} × {rule.rate} = {amount}; "
            f"rule {rule.rule_id} version {rule.version}."
        ),
        period_start=metric.period_start,
        period_end=metric.period_end,
        payment_recipient=rule.payment_recipient,
    )
    return FiscalCalculationResult(
        applicability=applicability,
        obligation=obligation,
        rule_id=rule.rule_id,
        title=rule.title,
        source_reference=rule.source_reference,
        position=FiscalPositionType.PAYABLE,
        net_amount=amount,
        currency=metric.currency,
        components=(
            FiscalCalculationComponent(
                code=rule.base_metric_code,
                title="Tax base",
                amount=normalize_money(metric.amount),
                currency=metric.currency,
            ),
        ),
        explanation=obligation.explanation,
    )


def _calculate_georgian_vat(
    rule: GeorgianVatRule,
    snapshot: FinancialSnapshot,
    *,
    as_of: date,
) -> FiscalCalculationResult:
    applicability = assess_rule_applicability(rule, snapshot, as_of=as_of)
    if applicability.status is not ApplicabilityStatus.APPLIED:
        return _empty_calculation(rule, applicability)

    turnover = _latest_metric(
        snapshot.metrics,
        rule.taxable_turnover_metric_code,
        as_of,
    )
    if turnover is None:
        return _empty_calculation(
            rule,
            ApplicabilityResult(
                status=ApplicabilityStatus.UNRESOLVED,
                reasons=("The VAT reporting-period turnover is missing.",),
                missing_fields=(
                    f"accounting_metric:{rule.taxable_turnover_metric_code}",
                ),
            ),
        )
    if not _is_calendar_month(turnover.period_start, turnover.period_end):
        return _empty_calculation(
            rule,
            ApplicabilityResult(
                status=ApplicabilityStatus.UNRESOLVED,
                reasons=("The Georgian VAT reporting period must be a calendar month.",),
                missing_fields=("valid_vat_reporting_period",),
            ),
        )

    metric_codes = (
        rule.deductible_input_vat_metric_code,
        rule.output_adjustment_metric_code,
        rule.import_vat_metric_code,
        rule.reverse_charge_vat_metric_code,
        rule.excluded_or_mixed_use_metric_code,
        rule.special_transaction_metric_code,
    )
    period_metrics: dict[str, AccountingMetric] = {
        rule.taxable_turnover_metric_code: turnover
    }
    missing: list[str] = []
    ambiguous: list[str] = []
    for code in metric_codes:
        matches = _metrics_for_period(
            snapshot.metrics,
            code,
            turnover.period_start,
            turnover.period_end,
        )
        if not matches:
            missing.append(f"accounting_metric:{code}")
        elif len(matches) > 1:
            ambiguous.append(f"unique_accounting_metric:{code}")
        else:
            period_metrics[code] = matches[0]
    if missing or ambiguous:
        return _empty_calculation(
            rule,
            ApplicabilityResult(
                status=ApplicabilityStatus.UNRESOLVED,
                reasons=(
                    "The VAT calculation requires one explicit value for every "
                    "component in the same reporting period.",
                ),
                missing_fields=tuple((*missing, *ambiguous)),
            ),
        )

    assert snapshot.company is not None
    invalid_currency = tuple(
        f"currency:{code}"
        for code, metric in period_metrics.items()
        if metric.currency != snapshot.company.base_currency
    )
    if invalid_currency:
        return _empty_calculation(
            rule,
            ApplicabilityResult(
                status=ApplicabilityStatus.UNRESOLVED,
                reasons=("VAT component currencies differ from company currency.",),
                missing_fields=invalid_currency,
            ),
        )

    negative = tuple(
        f"non_negative_metric:{code}"
        for code, metric in period_metrics.items()
        if metric.amount < Decimal("0.00")
    )
    if negative:
        return _empty_calculation(
            rule,
            ApplicabilityResult(
                status=ApplicabilityStatus.UNRESOLVED,
                reasons=("VAT components in this narrow model cannot be negative.",),
                missing_fields=negative,
            ),
        )

    excluded = period_metrics[rule.excluded_or_mixed_use_metric_code]
    special = period_metrics[rule.special_transaction_metric_code]
    unsupported = tuple(
        f"supported_scope:{code}"
        for code, metric in (
            (rule.excluded_or_mixed_use_metric_code, excluded),
            (rule.special_transaction_metric_code, special),
        )
        if metric.amount != Decimal("0.00")
    )
    if unsupported:
        return _empty_calculation(
            rule,
            ApplicabilityResult(
                status=ApplicabilityStatus.UNRESOLVED,
                reasons=(
                    "The period contains mixed, exempt, or special transactions "
                    "outside the implemented VAT calculation scope.",
                ),
                missing_fields=unsupported,
            ),
        )

    currency = snapshot.company.base_currency
    output_vat = normalize_money(turnover.amount * rule.rate)
    deductible = normalize_money(
        period_metrics[rule.deductible_input_vat_metric_code].amount
    )
    adjustment = normalize_money(
        period_metrics[rule.output_adjustment_metric_code].amount
    )
    import_vat = normalize_money(period_metrics[rule.import_vat_metric_code].amount)
    reverse_charge = normalize_money(
        period_metrics[rule.reverse_charge_vat_metric_code].amount
    )
    net_amount = normalize_money(
        output_vat + adjustment + import_vat + reverse_charge - deductible
    )
    components = (
        FiscalCalculationComponent(
            code="output_vat",
            title="Output VAT on standard-rate turnover",
            amount=output_vat,
            currency=currency,
        ),
        FiscalCalculationComponent(
            code="deductible_input_vat",
            title="Deductible input VAT",
            amount=-deductible,
            currency=currency,
        ),
        FiscalCalculationComponent(
            code="output_adjustment",
            title="Additional output VAT adjustments",
            amount=adjustment,
            currency=currency,
        ),
        FiscalCalculationComponent(
            code="import_vat",
            title="Import VAT payable",
            amount=import_vat,
            currency=currency,
        ),
        FiscalCalculationComponent(
            code="reverse_charge_vat",
            title="Reverse-charge VAT payable",
            amount=reverse_charge,
            currency=currency,
        ),
    )
    explanation = (
        f"({normalize_money(turnover.amount)} × {rule.rate}) + {adjustment} + "
        f"{import_vat} + {reverse_charge} − {deductible} = {net_amount}; "
        f"rule {rule.rule_id} version {rule.version}."
    )
    if net_amount <= Decimal("0.00"):
        return FiscalCalculationResult(
            applicability=applicability,
            obligation=None,
            rule_id=rule.rule_id,
            title=rule.title,
            source_reference=rule.source_reference,
            position=(
                FiscalPositionType.CREDIT
                if net_amount < Decimal("0.00")
                else FiscalPositionType.ZERO
            ),
            net_amount=net_amount,
            currency=currency,
            components=components,
            explanation=explanation,
        )

    due_date = _next_business_day(
        _following_month_day(
            turnover.period_end,
            rule.due_day_of_following_month,
        ),
        rule.non_business_dates,
    )
    obligation = FiscalObligation(
        obligation_key=(
            f"{rule.rule_id}:{turnover.period_start.isoformat()}:"
            f"{turnover.period_end.isoformat()}"
        ),
        rule_id=rule.rule_id,
        rule_version=rule.version,
        title=rule.title,
        amount=net_amount,
        currency=currency,
        due_date=due_date,
        category=rule.obligation_category,
        base_amount=normalize_money(turnover.amount),
        rate=rule.rate,
        source_reference=rule.source_reference,
        explanation=explanation,
        period_start=turnover.period_start,
        period_end=turnover.period_end,
        payment_recipient=rule.payment_recipient,
    )
    return FiscalCalculationResult(
        applicability=applicability,
        obligation=obligation,
        rule_id=rule.rule_id,
        title=rule.title,
        source_reference=rule.source_reference,
        position=FiscalPositionType.PAYABLE,
        net_amount=net_amount,
        currency=currency,
        components=components,
        explanation=explanation,
    )


def _empty_calculation(
    rule: FiscalObligationRule,
    applicability: ApplicabilityResult,
) -> FiscalCalculationResult:
    return FiscalCalculationResult(
        applicability=applicability,
        obligation=None,
        rule_id=rule.rule_id,
        title=rule.title,
        source_reference=rule.source_reference,
    )


def _is_calendar_month(period_start: date, period_end: date) -> bool:
    return (
        period_start.day == 1
        and period_start.year == period_end.year
        and period_start.month == period_end.month
        and period_end.day == monthrange(period_end.year, period_end.month)[1]
    )


def _metrics_for_period(
    metrics: tuple[AccountingMetric, ...],
    code: str,
    period_start: date,
    period_end: date,
) -> tuple[AccountingMetric, ...]:
    return tuple(
        metric
        for metric in metrics
        if metric.code == code
        and metric.period_start == period_start
        and metric.period_end == period_end
    )


def _following_month_day(period_end: date, day: int) -> date:
    if not 1 <= day <= 28:
        raise ValueError("A stable following-month due day must be between 1 and 28.")
    if period_end.month == 12:
        return date(period_end.year + 1, 1, day)
    return date(period_end.year, period_end.month + 1, day)


def _next_business_day(value: date, non_business_dates: frozenset[date]) -> date:
    while value.weekday() >= 5 or value in non_business_dates:
        value += timedelta(days=1)
    return value


def reconcile_fiscal_obligation(
    obligation: FiscalObligation,
    events: tuple[FinancialEvent, ...],
) -> ReconciliationResult:
    matching = tuple(
        event
        for event in events
        if event.obligation_key == obligation.obligation_key
        and event.status is not FinancialEventStatus.CANCELLED
    )
    if not matching:
        return ReconciliationResult(
            action=ReconciliationAction.ADD_OBLIGATION,
            obligation=obligation,
            matching_event_ids=(),
            outstanding_amount=obligation.amount,
            forecast_due_date=obligation.due_date,
        )

    paid_amount = normalize_money(sum(
        (event.settled_amount for event in matching),
        start=Decimal("0.00"),
    ))
    if all(event.status is FinancialEventStatus.SETTLED for event in matching):
        paid_amount = max(paid_amount, obligation.amount)
    outstanding = normalize_money(max(obligation.amount - paid_amount, Decimal("0.00")))
    action = (
        ReconciliationAction.ALREADY_SETTLED
        if outstanding == Decimal("0.00")
        else ReconciliationAction.USE_EXISTING
    )
    return ReconciliationResult(
        action=action,
        obligation=obligation,
        matching_event_ids=tuple(event.external_id for event in matching),
        outstanding_amount=outstanding,
        forecast_due_date=min(event.due_date for event in matching),
    )


def _latest_metric(
    metrics: tuple[AccountingMetric, ...],
    code: str,
    as_of: date,
) -> AccountingMetric | None:
    candidates = [
        metric for metric in metrics if metric.code == code and metric.period_end <= as_of
    ]
    return max(candidates, key=lambda metric: metric.period_end, default=None)
