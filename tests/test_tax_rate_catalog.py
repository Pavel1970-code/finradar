import json
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from finradar.domain.tax_rate_catalog import (
    TaxRateValueKind,
    TaxRuleCoverage,
    validate_tax_rate_catalog,
)
from finradar.infrastructure.obligation_catalog_repository import (
    ObligationCatalogRepository,
)
from finradar.infrastructure.tax_rate_catalog_repository import (
    TaxRateCatalogError,
    TaxRateCatalogRepository,
)


CATALOG_PATH = (
    Path(__file__).parents[1]
    / "src"
    / "finradar"
    / "regulatory"
    / "catalogs"
    / "georgia_tax_rates_v1.json"
)


def test_georgian_tax_rate_catalog_is_versioned_and_covers_all_taxes() -> None:
    catalog = TaxRateCatalogRepository().load_georgia()

    assert catalog.catalog_id == "georgia-tax-rates"
    assert catalog.version == 1
    assert catalog.verified_on == date(2026, 7, 25)
    assert len(catalog.rules) == 16
    assert {
        item.instrument_id
        for item in catalog.rules
        if item.instrument_id.startswith("ge-tax-")
    } >= {
        "ge-tax-income",
        "ge-tax-profit",
        "ge-tax-vat",
        "ge-tax-excise",
        "ge-tax-import",
        "ge-tax-property",
    }
    assert all(
        source.url.startswith("https://matsne.gov.ge/")
        for source in catalog.sources
    )


def test_scalar_rates_match_the_verified_tax_code_baseline() -> None:
    catalog = TaxRateCatalogRepository().load_georgia()

    income = catalog.rule("ge-income-standard")
    vat = catalog.rule("ge-vat-standard")
    profit = catalog.rule("ge-profit-rates")
    small = catalog.rule("ge-income-small-business")

    assert income.components[0].value == Decimal("0.20")
    assert vat.components[0].value == Decimal("0.18")
    assert {item.value for item in profit.components} == {
        Decimal("0.05"),
        Decimal("0.10"),
        Decimal("0.15"),
        Decimal("0.20"),
    }
    assert tuple(item.value for item in small.components) == (
        Decimal("0.01"),
        Decimal("0.03"),
    )
    assert "500 000 GEL" in small.components[1].condition_ru
    assert "700 000 GEL" in small.components[1].condition_ru


def test_complex_schedules_cannot_claim_deterministic_coverage() -> None:
    catalog = TaxRateCatalogRepository().load_georgia()

    excise = catalog.rule("ge-excise-classification-schedule")
    imports = catalog.rule("ge-import-rate-schedule")
    land = catalog.rule("ge-property-land")

    assert excise.coverage is TaxRuleCoverage.REFERENCE_ONLY
    assert imports.coverage is TaxRuleCoverage.REFERENCE_ONLY
    assert land.coverage is TaxRuleCoverage.REFERENCE_ONLY
    assert any(
        component.value_kind is TaxRateValueKind.CLASSIFICATION_SCHEDULE
        for rule in (excise, imports, land)
        for component in rule.components
    )


def test_each_rate_rule_is_linked_from_its_obligation() -> None:
    rates = TaxRateCatalogRepository().load_georgia()
    obligations = ObligationCatalogRepository().load_georgia()

    for rule in rates.rules:
        assert rule.rule_id in obligations.entry(rule.instrument_id).rate_rule_ids


def test_rate_rule_selection_is_date_bound() -> None:
    catalog = TaxRateCatalogRepository().load_georgia()

    selected = catalog.rule_at("ge-vat-standard", date(2026, 8, 1))

    assert selected.rule_version == 1
    with pytest.raises(LookupError, match="found 0"):
        catalog.rule_at("ge-vat-standard", date(2026, 7, 24))


def test_required_fact_ids_make_missing_accounting_data_machine_readable() -> None:
    catalog = TaxRateCatalogRepository().load_georgia()
    small = catalog.rule("ge-income-small-business")

    missing = small.missing_required_fact_ids(
        frozenset(
            {
                "small_business_status",
                "activity_type",
                "current_month_taxable_income",
            }
        )
    )

    assert missing == (
        "year_to_date_income_before_month",
        "wine_or_agrotourism_status",
        "special_regime_excluded_income",
    )


def test_overlapping_versions_are_rejected() -> None:
    catalog = TaxRateCatalogRepository().load_georgia()
    original = catalog.rule("ge-vat-standard")
    first = replace(original, valid_through=date(2026, 12, 31))
    overlapping = replace(
        original,
        rule_version=2,
        valid_from=date(2026, 12, 31),
        supersedes_version=1,
    )
    broken = replace(
        catalog,
        rules=tuple(
            item for item in catalog.rules if item.rule_id != "ge-vat-standard"
        )
        + (first, overlapping),
    )
    known_instruments = frozenset(
        item.instrument_id
        for item in ObligationCatalogRepository().load_georgia().entries
    )

    with pytest.raises(ValueError, match="overlapping"):
        validate_tax_rate_catalog(
            broken,
            known_instrument_ids=known_instruments,
        )


def test_rate_catalog_checksum_rejects_modified_rate(tmp_path: Path) -> None:
    raw = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    raw["payload"]["rules"][0]["components"][0]["value"] = "0.19"
    target = tmp_path / CATALOG_PATH.name
    target.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(TaxRateCatalogError, match="integrity"):
        TaxRateCatalogRepository(tmp_path).load_georgia()
