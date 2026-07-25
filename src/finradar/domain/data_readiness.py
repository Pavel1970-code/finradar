from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum

from finradar.domain.financial_snapshot import (
    DatasetKind,
    FinancialEventKind,
    FinancialEventStatus,
    FinancialSnapshot,
    SourceIssueSeverity,
)
from finradar.domain.georgia_payroll import (
    CURRENT_GEORGIA_PAYROLL_RULES,
    PayrollCheckSeverity,
    validate_georgian_payroll_record,
)
from finradar.domain.payroll import PayrollRecordStatus


class ReadinessStatus(str, Enum):
    READY = "ready"
    LIMITED = "limited"
    BLOCKED = "blocked"


class IssueSeverity(str, Enum):
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class DataIssue:
    code: str
    severity: IssueSeverity
    dataset: DatasetKind
    message: str
    impact: str
    source_reference: str = ""


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    status: ReadinessStatus
    issues: tuple[DataIssue, ...]


def assess_forecast_readiness(
    snapshot: FinancialSnapshot,
    *,
    as_of: date,
    maximum_balance_age_days: int = 1,
) -> ReadinessReport:
    issues: list[DataIssue] = []

    issues.extend(
        DataIssue(
            code=issue.code,
            severity=(
                IssueSeverity.ERROR
                if issue.severity is SourceIssueSeverity.ERROR
                else IssueSeverity.WARNING
            ),
            dataset=issue.dataset,
            message=issue.message,
            impact=issue.impact,
            source_reference=issue.source_reference,
        )
        for issue in snapshot.source_issues
    )

    if not snapshot.supplies(DatasetKind.COMPANY_PROFILE) or snapshot.company is None:
        issues.append(
            DataIssue(
                code="company_profile_missing",
                severity=IssueSeverity.ERROR,
                dataset=DatasetKind.COMPANY_PROFILE,
                message="Company profile was not supplied by the accounting source.",
                impact="Fiscal applicability and company-level forecast cannot be determined.",
            )
        )

    if not snapshot.supplies(DatasetKind.ACCOUNT_BALANCES):
        issues.append(
            DataIssue(
                code="account_balances_unavailable",
                severity=IssueSeverity.ERROR,
                dataset=DatasetKind.ACCOUNT_BALANCES,
                message="Account balances are unavailable.",
                impact="The opening cash position cannot be calculated.",
            )
        )
    elif not snapshot.balances:
        issues.append(
            DataIssue(
                code="account_balances_empty",
                severity=IssueSeverity.ERROR,
                dataset=DatasetKind.ACCOUNT_BALANCES,
                message="The source returned no active cash accounts.",
                impact="The opening cash position cannot be calculated.",
            )
        )
    else:
        oldest_allowed = as_of.toordinal() - maximum_balance_age_days
        if any(balance.balance_date.toordinal() < oldest_allowed for balance in snapshot.balances):
            issues.append(
                DataIssue(
                    code="account_balance_stale",
                    severity=IssueSeverity.WARNING,
                    dataset=DatasetKind.ACCOUNT_BALANCES,
                    message="At least one account balance is older than the accepted limit.",
                    impact="The forecast starts from a potentially outdated cash position.",
                )
            )

        if snapshot.company is not None and any(
            balance.currency != snapshot.company.base_currency
            for balance in snapshot.balances
        ):
            issues.append(
                DataIssue(
                    code="account_currency_incompatible",
                    severity=IssueSeverity.ERROR,
                    dataset=DatasetKind.ACCOUNT_BALANCES,
                    message="At least one account uses a currency other than the base currency.",
                    impact="A consolidated forecast requires an explicit conversion policy.",
                )
            )

    if not snapshot.supplies(DatasetKind.PAYMENT_CALENDAR):
        issues.append(
            DataIssue(
                code="payment_calendar_unavailable",
                severity=IssueSeverity.WARNING,
                dataset=DatasetKind.PAYMENT_CALENDAR,
                message="The payment calendar was not supplied by the accounting source.",
                impact="Future inflows and payments may be missing from the forecast.",
            )
        )
    elif snapshot.company is not None and any(
        event.currency != snapshot.company.base_currency
        for event in snapshot.events
    ):
        issues.append(
            DataIssue(
                code="event_currency_incompatible",
                severity=IssueSeverity.ERROR,
                dataset=DatasetKind.PAYMENT_CALENDAR,
                message="At least one payment-calendar event uses another currency.",
                impact="The event cannot be included without an explicit conversion policy.",
            )
        )

    if snapshot.supplies(DatasetKind.PAYMENT_CALENDAR):
        planned_events = tuple(
            event
            for event in snapshot.events
            if event.kind is FinancialEventKind.PLANNED
            and event.status is not FinancialEventStatus.CANCELLED
        )
        for event in planned_events:
            reference = event.source_reference or event.external_id
            if event.counterparty is None:
                issues.append(
                    DataIssue(
                        code="payment_counterparty_missing",
                        severity=IssueSeverity.WARNING,
                        dataset=DatasetKind.PAYMENT_CALENDAR,
                        message=(
                            f'Для операции «{event.title}» не указан контрагент.'
                        ),
                        impact=(
                            "Сумма учитывается в прогнозе, но пользователь не видит, "
                            "кто должен заплатить или кому предназначена выплата."
                        ),
                        source_reference=reference,
                    )
                )
            if event.payment_basis is None:
                issues.append(
                    DataIssue(
                        code="payment_basis_missing",
                        severity=IssueSeverity.WARNING,
                        dataset=DatasetKind.PAYMENT_CALENDAR,
                        message=(
                            f'Для операции «{event.title}» не указан документ-основание.'
                        ),
                        impact=(
                            "Сумма учитывается в прогнозе, но её нельзя связать "
                            "со счётом, договором, накладной или расчётной ведомостью."
                        ),
                        source_reference=reference,
                    )
                )
            if event.settled_amount > event.amount:
                issues.append(
                    DataIssue(
                        code="payment_settlement_exceeds_amount",
                        severity=IssueSeverity.ERROR,
                        dataset=DatasetKind.PAYMENT_CALENDAR,
                        message=(
                            f'По операции «{event.title}» оплаченная сумма превышает '
                            "сумму обязательства."
                        ),
                        impact=(
                            "Остаток обязательства неоднозначен; прогноз заблокирован "
                            "до исправления исходных данных."
                        ),
                        source_reference=reference,
                    )
                )
            if (event.period_start is None) != (event.period_end is None):
                issues.append(
                    DataIssue(
                        code="payment_period_incomplete",
                        severity=IssueSeverity.WARNING,
                        dataset=DatasetKind.PAYMENT_CALENDAR,
                        message=(
                            f'Для операции «{event.title}» расчётный период указан '
                            "не полностью."
                        ),
                        impact=(
                            "Платёж можно учесть по дате и сумме, но нельзя однозначно "
                            "объяснить, за какой период он начислен."
                        ),
                        source_reference=reference,
                    )
                )
            elif (
                event.period_start is not None
                and event.period_end is not None
                and event.period_end < event.period_start
            ):
                issues.append(
                    DataIssue(
                        code="payment_period_inverted",
                        severity=IssueSeverity.ERROR,
                        dataset=DatasetKind.PAYMENT_CALENDAR,
                        message=f'У операции «{event.title}» перепутаны границы периода.',
                        impact=(
                            "Период обязательства некорректен; прогноз заблокирован "
                            "до исправления исходных данных."
                        ),
                        source_reference=reference,
                    )
                )

        if (
            snapshot.company is not None
            and snapshot.company.jurisdiction == "GE"
        ):
            aggregate_payroll_events = tuple(
                event
                for event in planned_events
                if event.category in {"payroll", "payroll_aggregate"}
            )
            if aggregate_payroll_events and not snapshot.payroll_records:
                event = aggregate_payroll_events[0]
                issues.append(
                    DataIssue(
                        code="payroll_breakdown_unavailable",
                        severity=IssueSeverity.WARNING,
                        dataset=DatasetKind.PAYROLL,
                        message=(
                            f'Для операции «{event.title}» не передано локальное разложение '
                            "зарплаты на чистую выплату, налог и пенсионные взносы."
                        ),
                        impact=(
                            "Сумма события учитывается как единый расход, но FinRadar "
                            "пока не может проверить удержанный подоходный налог, "
                            "долю работника и дополнительный пенсионный расход "
                            "работодателя."
                        ),
                        source_reference=event.source_reference or event.external_id,
                    )
                )
            if snapshot.supplies(DatasetKind.PAYROLL) and not snapshot.payroll_records:
                issues.append(
                    DataIssue(
                        code="payroll_records_empty",
                        severity=IssueSeverity.WARNING,
                        dataset=DatasetKind.PAYROLL,
                        message="Источник заявил зарплатный набор, но не передал ни одной строки.",
                        impact="Зарплатные налоги и пенсионные суммы нельзя проверить.",
                    )
                )
            for record in snapshot.payroll_records:
                for check in validate_georgian_payroll_record(
                    record,
                    CURRENT_GEORGIA_PAYROLL_RULES,
                ):
                    issues.append(
                        DataIssue(
                            code=check.code,
                            severity=(
                                IssueSeverity.ERROR
                                if check.severity is PayrollCheckSeverity.ERROR
                                else IssueSeverity.WARNING
                            ),
                            dataset=DatasetKind.PAYROLL,
                            message=check.message,
                            impact=check.impact,
                            source_reference=check.source_reference,
                        )
                    )
            active_payroll = tuple(
                record
                for record in snapshot.payroll_records
                if record.status
                not in {PayrollRecordStatus.CANCELLED, PayrollRecordStatus.PAID}
            )
            if any(
                record.status is PayrollRecordStatus.PARTIALLY_PAID
                for record in active_payroll
            ):
                issues.append(
                    DataIssue(
                        code="payroll_partial_settlement_details_missing",
                        severity=IssueSeverity.WARNING,
                        dataset=DatasetKind.PAYROLL,
                        message="Есть частично оплаченная зарплатная строка без разложения погашения.",
                        impact="Остатки чистой зарплаты, налога и пенсии нельзя определить отдельно.",
                    )
                )
            if active_payroll and aggregate_payroll_events:
                issues.append(
                    DataIssue(
                        code="payroll_aggregate_conflicts_with_breakdown",
                        severity=IssueSeverity.ERROR,
                        dataset=DatasetKind.PAYMENT_CALENDAR,
                        message="В платёжном календаре одновременно присутствуют агрегированная зарплата и её локальное разложение.",
                        impact="Использование обеих форм задвоит денежный расход.",
                    )
                )
            elif active_payroll:
                _check_payroll_cash_components(
                    active_payroll,
                    planned_events,
                    issues,
                )

    if not snapshot.supplies(DatasetKind.ACCOUNTING_FACTS):
        issues.append(
            DataIssue(
                code="accounting_facts_unavailable",
                severity=IssueSeverity.WARNING,
                dataset=DatasetKind.ACCOUNTING_FACTS,
                message="Accounting facts required for fiscal analysis are unavailable.",
                impact="Fiscal obligations may remain unresolved.",
            )
        )

    if snapshot.company is not None:
        if snapshot.company.jurisdiction is None:
            issues.append(
                DataIssue(
                    code="jurisdiction_missing",
                    severity=IssueSeverity.WARNING,
                    dataset=DatasetKind.COMPANY_PROFILE,
                    message="Company jurisdiction is unknown.",
                    impact="Applicable fiscal rules cannot be selected.",
                )
            )
        if snapshot.company.tax_regime is None:
            issues.append(
                DataIssue(
                    code="tax_regime_missing",
                    severity=IssueSeverity.WARNING,
                    dataset=DatasetKind.COMPANY_PROFILE,
                    message="Company tax regime is unknown.",
                    impact="Tax obligations and benefits cannot be calculated reliably.",
                )
            )

    if any(issue.severity is IssueSeverity.ERROR for issue in issues):
        status = ReadinessStatus.BLOCKED
    elif issues:
        status = ReadinessStatus.LIMITED
    else:
        status = ReadinessStatus.READY

    return ReadinessReport(status=status, issues=tuple(issues))


def _check_payroll_cash_components(
    records,
    planned_events,
    issues: list[DataIssue],
) -> None:
    expected = {
        "payroll_net_salary": sum(
            (item.net_salary_payable for item in records),
            start=Decimal("0"),
        ),
        "payroll_income_tax": sum(
            (item.income_tax_withheld for item in records),
            start=Decimal("0"),
        ),
        "payroll_pension": sum(
            (item.pension_remittance_payable for item in records),
            start=Decimal("0"),
        ),
        "payroll_other_withholding": sum(
            (item.other_employee_withholdings for item in records),
            start=Decimal("0"),
        ),
        "payroll_employer_other_cost": sum(
            (item.employer_other_costs for item in records),
            start=Decimal("0"),
        ),
    }
    for category, expected_amount in expected.items():
        if expected_amount == 0:
            continue
        actual_amount = sum(
            (
                event.amount
                for event in planned_events
                if event.category == category
            ),
            start=Decimal("0"),
        )
        if actual_amount == expected_amount:
            continue
        issues.append(
            DataIssue(
                code=f"{category}_calendar_mismatch",
                severity=IssueSeverity.WARNING,
                dataset=DatasetKind.PAYMENT_CALENDAR,
                message=(
                    f"Сумма компонента «{category}» в платёжном календаре "
                    "не совпадает с зарплатным набором."
                ),
                impact=(
                    "Прогноз использует платёжный календарь, поэтому зарплатный "
                    "денежный поток может быть неполным или задвоенным."
                ),
            )
        )
