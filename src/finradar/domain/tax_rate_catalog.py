from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum

from finradar.domain.obligation_catalog import LegalSource


class TaxRateValueKind(str, Enum):
    PERCENTAGE = "percentage"
    FIXED_AMOUNT = "fixed_amount"
    AMOUNT_RANGE = "amount_range"
    FORMULA = "formula"
    CLASSIFICATION_SCHEDULE = "classification_schedule"
    EXEMPTION = "exemption"


class TaxRuleCoverage(str, Enum):
    DETERMINISTIC = "deterministic"
    CONDITIONAL = "conditional"
    REFERENCE_ONLY = "reference_only"


@dataclass(frozen=True, slots=True)
class TaxRateComponent:
    component_id: str
    label_ru: str
    value_kind: TaxRateValueKind
    value: Decimal | None = None
    minimum_value: Decimal | None = None
    maximum_value: Decimal | None = None
    currency: str | None = None
    unit: str | None = None
    condition_code: str = ""
    condition_ru: str = ""
    note: str = ""


@dataclass(frozen=True, slots=True)
class TaxRateRule:
    rule_id: str
    rule_version: int
    instrument_id: str
    title_ru: str
    valid_from: date
    valid_through: date | None
    coverage: TaxRuleCoverage
    taxable_base_ru: str
    calculation_method_ru: str
    applicability_ru: str
    required_fact_ids: tuple[str, ...]
    required_facts: tuple[str, ...]
    components: tuple[TaxRateComponent, ...]
    source_ids: tuple[str, ...]
    source_provisions: tuple[str, ...]
    supersedes_version: int | None = None
    note: str = ""

    def applies_on(self, target_date: date) -> bool:
        return self.valid_from <= target_date and (
            self.valid_through is None or target_date <= self.valid_through
        )

    def missing_required_fact_ids(
        self,
        available_fact_ids: frozenset[str],
    ) -> tuple[str, ...]:
        return tuple(
            fact_id
            for fact_id in self.required_fact_ids
            if fact_id not in available_fact_ids
        )


@dataclass(frozen=True, slots=True)
class TaxRateCatalog:
    catalog_id: str
    version: int
    jurisdiction: str
    verified_on: date
    sources: tuple[LegalSource, ...]
    rules: tuple[TaxRateRule, ...]

    def rule(self, rule_id: str, *, version: int | None = None) -> TaxRateRule:
        matches = tuple(
            item
            for item in self.rules
            if item.rule_id == rule_id
            and (version is None or item.rule_version == version)
        )
        if not matches:
            raise LookupError(f"Unknown tax-rate rule: {rule_id}.")
        if version is None and len(matches) != 1:
            raise LookupError(
                f"Tax-rate rule {rule_id} has multiple versions; specify version."
            )
        return matches[0]

    def rules_for(self, instrument_id: str) -> tuple[TaxRateRule, ...]:
        return tuple(
            item for item in self.rules if item.instrument_id == instrument_id
        )

    def rule_at(self, rule_id: str, target_date: date) -> TaxRateRule:
        matches = tuple(
            item
            for item in self.rules
            if item.rule_id == rule_id and item.applies_on(target_date)
        )
        if len(matches) != 1:
            raise LookupError(
                f"Expected one version of {rule_id} on {target_date}, "
                f"found {len(matches)}."
            )
        return matches[0]


def validate_tax_rate_catalog(
    catalog: TaxRateCatalog,
    *,
    known_instrument_ids: frozenset[str],
) -> TaxRateCatalog:
    if catalog.version < 1:
        raise ValueError("Tax-rate catalog version must be positive.")
    if catalog.jurisdiction != "GE":
        raise ValueError("This tax-rate catalog contract currently supports Georgia only.")

    source_ids = tuple(item.source_id for item in catalog.sources)
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("Tax-rate source identifiers must be unique.")
    known_sources = set(source_ids)

    keys = tuple((item.rule_id, item.rule_version) for item in catalog.rules)
    if len(keys) != len(set(keys)):
        raise ValueError("Tax-rate rule ID and version pairs must be unique.")

    component_ids: set[tuple[str, int, str]] = set()
    for rule in catalog.rules:
        if rule.rule_version < 1:
            raise ValueError(f"Tax-rate rule {rule.rule_id} has an invalid version.")
        if rule.instrument_id not in known_instrument_ids:
            raise ValueError(
                f"Tax-rate rule {rule.rule_id} references an unknown instrument."
            )
        if rule.valid_through is not None and rule.valid_through < rule.valid_from:
            raise ValueError(f"Tax-rate rule {rule.rule_id} has an invalid period.")
        if not rule.required_fact_ids or not rule.required_facts:
            raise ValueError(f"Tax-rate rule {rule.rule_id} has no required facts.")
        if len(rule.required_fact_ids) != len(rule.required_facts):
            raise ValueError(
                f"Tax-rate rule {rule.rule_id} has inconsistent required facts."
            )
        if len(rule.required_fact_ids) != len(set(rule.required_fact_ids)):
            raise ValueError(
                f"Tax-rate rule {rule.rule_id} has duplicate required facts."
            )
        if not rule.source_ids or not set(rule.source_ids) <= known_sources:
            raise ValueError(f"Tax-rate rule {rule.rule_id} has invalid sources.")
        if not rule.source_provisions:
            raise ValueError(f"Tax-rate rule {rule.rule_id} has no legal provisions.")
        if not rule.components:
            raise ValueError(f"Tax-rate rule {rule.rule_id} has no components.")
        if (
            rule.supersedes_version is not None
            and rule.supersedes_version >= rule.rule_version
        ):
            raise ValueError(
                f"Tax-rate rule {rule.rule_id} has an invalid predecessor."
            )
        for component in rule.components:
            component_key = (
                rule.rule_id,
                rule.rule_version,
                component.component_id,
            )
            if component_key in component_ids:
                raise ValueError(
                    f"Tax-rate rule {rule.rule_id} has duplicate components."
                )
            component_ids.add(component_key)
            _validate_component(rule, component)

    _validate_version_periods(catalog.rules)
    _validate_tax_coverage(catalog)
    return catalog


def _validate_component(
    rule: TaxRateRule,
    component: TaxRateComponent,
) -> None:
    if component.value is not None and component.value < 0:
        raise ValueError(f"Tax-rate component {component.component_id} is negative.")
    if component.minimum_value is not None and component.minimum_value < 0:
        raise ValueError(f"Tax-rate component {component.component_id} is negative.")
    if component.maximum_value is not None and component.maximum_value < 0:
        raise ValueError(f"Tax-rate component {component.component_id} is negative.")
    if (
        component.minimum_value is not None
        and component.maximum_value is not None
        and component.maximum_value < component.minimum_value
    ):
        raise ValueError(
            f"Tax-rate component {component.component_id} has an invalid range."
        )
    if component.value_kind is TaxRateValueKind.PERCENTAGE:
        if component.value is None or component.value > 1:
            raise ValueError(
                f"Percentage component {component.component_id} is invalid."
            )
    elif component.value_kind is TaxRateValueKind.FIXED_AMOUNT:
        if component.value is None or component.currency is None:
            raise ValueError(
                f"Fixed-amount component {component.component_id} is incomplete."
            )
    elif component.value_kind is TaxRateValueKind.AMOUNT_RANGE:
        if component.minimum_value is None and component.maximum_value is None:
            raise ValueError(
                f"Range component {component.component_id} has no bounds."
            )
    elif component.value_kind in {
        TaxRateValueKind.FORMULA,
        TaxRateValueKind.CLASSIFICATION_SCHEDULE,
    }:
        if not component.note:
            raise ValueError(
                f"Non-scalar component {component.component_id} needs a formula note."
            )
    elif component.value_kind is TaxRateValueKind.EXEMPTION:
        if any(
            value is not None
            for value in (
                component.value,
                component.minimum_value,
                component.maximum_value,
            )
        ):
            raise ValueError(
                f"Exemption component {component.component_id} must not carry a rate."
            )

    if (
        rule.coverage is TaxRuleCoverage.DETERMINISTIC
        and component.value_kind is TaxRateValueKind.CLASSIFICATION_SCHEDULE
    ):
        raise ValueError(
            f"Deterministic rule {rule.rule_id} cannot depend on an unencoded schedule."
        )


def _validate_version_periods(rules: tuple[TaxRateRule, ...]) -> None:
    by_rule: dict[str, list[TaxRateRule]] = {}
    for rule in rules:
        by_rule.setdefault(rule.rule_id, []).append(rule)
    for rule_id, versions in by_rule.items():
        versions.sort(key=lambda item: item.valid_from)
        for previous, current in zip(versions, versions[1:]):
            if previous.valid_through is None:
                raise ValueError(
                    f"Tax-rate rule {rule_id} has an open version before another version."
                )
            if current.valid_from <= previous.valid_through:
                raise ValueError(
                    f"Tax-rate rule {rule_id} has overlapping versions."
                )


def _validate_tax_coverage(catalog: TaxRateCatalog) -> None:
    expected_tax_ids = {
        "ge-tax-income",
        "ge-tax-profit",
        "ge-tax-vat",
        "ge-tax-excise",
        "ge-tax-import",
        "ge-tax-property",
    }
    represented = {
        item.instrument_id for item in catalog.rules if item.instrument_id in expected_tax_ids
    }
    if represented != expected_tax_ids:
        raise ValueError("Tax-rate catalog must represent all six Georgian taxes.")
