from dataclasses import dataclass
from datetime import date

from finradar.domain.tax_profile import (
    CompanyTaxProfile,
    TaxProfileAssessment,
    derived_tax_profile_facts,
)
from finradar.domain.tax_rate_catalog import TaxRateRule
from finradar.domain.data_readiness import (
    DataIssue,
    IssueSeverity,
    ReadinessReport,
    ReadinessStatus,
)
from finradar.domain.financial_snapshot import DatasetKind


@dataclass(frozen=True, slots=True)
class MissingTaxFact:
    fact_id: str
    label_ru: str


@dataclass(frozen=True, slots=True)
class TaxRuleFactReadiness:
    rule_id: str
    ready: bool
    available_fact_ids: frozenset[str]
    missing_facts: tuple[MissingTaxFact, ...]


def assess_tax_rule_facts(
    rule: TaxRateRule,
    profile: CompanyTaxProfile,
    *,
    on_date: date,
    transaction_fact_ids: frozenset[str] = frozenset(),
    regulatory_fact_ids: frozenset[str] = frozenset(),
) -> TaxRuleFactReadiness:
    profile_facts = derived_tax_profile_facts(profile, on_date=on_date)
    available = (
        frozenset(profile_facts)
        | transaction_fact_ids
        | regulatory_fact_ids
    )
    labels = dict(zip(rule.required_fact_ids, rule.required_facts))
    missing_ids = rule.missing_required_fact_ids(available)
    missing = tuple(
        MissingTaxFact(fact_id=fact_id, label_ru=labels[fact_id])
        for fact_id in missing_ids
    )
    return TaxRuleFactReadiness(
        rule_id=rule.rule_id,
        ready=not missing,
        available_fact_ids=available,
        missing_facts=missing,
    )


def include_tax_profile_readiness(
    report: ReadinessReport,
    assessment: TaxProfileAssessment,
) -> ReadinessReport:
    """Adds tax-profile limitations without blocking the cash-only forecast."""

    tax_issues = [
        DataIssue(
            code=f"tax_profile_fact_missing:{question.fact_id}",
            severity=IssueSeverity.WARNING,
            dataset=DatasetKind.COMPANY_PROFILE,
            message=f"Не указан налоговый параметр: {question.text_ru}",
            impact=(
                "Кассовый прогноз доступен, но связанные налоговые обязательства "
                "нельзя рассчитать полностью."
            ),
            source_reference=question.question_id,
        )
        for question in assessment.unanswered_required_questions
    ]
    tax_issues.extend(
        DataIssue(
            code=f"tax_profile_finding:{finding.code}",
            severity=IssueSeverity.WARNING,
            dataset=DatasetKind.COMPANY_PROFILE,
            message=finding.message_ru,
            impact=(
                "Кассовый прогноз доступен, но налоговая часть требует проверки "
                "настроек компании."
            ),
        )
        for finding in assessment.findings
    )
    base_issues = tuple(
        item
        for item in report.issues
        if not item.code.startswith("tax_profile_")
    )
    if not tax_issues:
        if base_issues == report.issues:
            return report
        status = (
            ReadinessStatus.BLOCKED
            if any(item.severity is IssueSeverity.ERROR for item in base_issues)
            else ReadinessStatus.LIMITED
            if base_issues
            else ReadinessStatus.READY
        )
        return ReadinessReport(status=status, issues=base_issues)
    status = (
        ReadinessStatus.BLOCKED
        if report.status is ReadinessStatus.BLOCKED
        else ReadinessStatus.LIMITED
    )
    return ReadinessReport(status=status, issues=base_issues + tuple(tax_issues))
