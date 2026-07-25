from dataclasses import dataclass
from datetime import date

from finradar.domain.tax_profile import (
    CompanyTaxProfile,
    derived_tax_profile_facts,
)
from finradar.domain.tax_rate_catalog import TaxRateRule


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
