from dataclasses import dataclass
from datetime import date
from enum import Enum

from finradar.domain.financial_snapshot import DatasetKind, FinancialSnapshot


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
