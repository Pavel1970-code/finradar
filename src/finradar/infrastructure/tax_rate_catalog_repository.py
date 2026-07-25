from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal
from importlib import resources
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from finradar.domain.obligation_catalog import LegalSource, MandatoryObligationCatalog
from finradar.domain.tax_rate_catalog import (
    TaxRateCatalog,
    TaxRateComponent,
    TaxRateRule,
    TaxRateValueKind,
    TaxRuleCoverage,
    validate_tax_rate_catalog,
)
from finradar.infrastructure.obligation_catalog_repository import (
    ObligationCatalogRepository,
)


TAX_RATE_CATALOG_SCHEMA_VERSION = 1


class TaxRateCatalogError(ValueError):
    """Raised when a bundled tax-rate catalog is invalid or corrupted."""


class _ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _SourceData(_ContractModel):
    source_id: str
    title: str
    url: str
    provisions: tuple[str, ...] = ()
    note: str = ""


class _ComponentData(_ContractModel):
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


class _RuleData(_ContractModel):
    rule_id: str
    rule_version: int = Field(ge=1)
    instrument_id: str
    title_ru: str
    valid_from: date
    valid_through: date | None = None
    coverage: TaxRuleCoverage
    taxable_base_ru: str
    calculation_method_ru: str
    applicability_ru: str
    required_fact_ids: tuple[str, ...]
    required_facts: tuple[str, ...]
    components: tuple[_ComponentData, ...]
    source_ids: tuple[str, ...]
    source_provisions: tuple[str, ...]
    supersedes_version: int | None = Field(default=None, ge=1)
    note: str = ""


class _CatalogPayload(_ContractModel):
    jurisdiction: str
    verified_on: date
    sources: tuple[_SourceData, ...]
    rules: tuple[_RuleData, ...]


class _CatalogEnvelope(_ContractModel):
    schema_version: int
    catalog_id: str
    catalog_version: int = Field(ge=1)
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    payload: _CatalogPayload


class TaxRateCatalogRepository:
    def __init__(
        self,
        resource_directory: Path | None = None,
        *,
        obligation_repository: ObligationCatalogRepository | None = None,
    ) -> None:
        self._resource_directory = resource_directory
        self._obligation_repository = (
            obligation_repository or ObligationCatalogRepository()
        )

    def load_georgia(self, *, version: int = 1) -> TaxRateCatalog:
        filename = f"georgia_tax_rates_v{version}.json"
        try:
            content = self._read_text(filename)
        except FileNotFoundError as error:
            raise TaxRateCatalogError(
                f"Unknown Georgian tax-rate catalog version: {version}."
            ) from error
        try:
            raw = json.loads(content)
            envelope = _CatalogEnvelope.model_validate(raw)
        except (json.JSONDecodeError, TypeError, ValueError) as error:
            raise TaxRateCatalogError("Tax-rate catalog contract is invalid.") from error
        if envelope.schema_version != TAX_RATE_CATALOG_SCHEMA_VERSION:
            raise TaxRateCatalogError("Unsupported tax-rate catalog schema.")
        if envelope.catalog_id != "georgia-tax-rates":
            raise TaxRateCatalogError("Tax-rate catalog ID is invalid.")
        if envelope.catalog_version != version:
            raise TaxRateCatalogError(
                "Tax-rate catalog version does not match its filename."
            )
        if _payload_hash(raw.get("payload")) != envelope.payload_sha256:
            raise TaxRateCatalogError("Tax-rate catalog integrity check failed.")

        payload = envelope.payload
        catalog = TaxRateCatalog(
            catalog_id=envelope.catalog_id,
            version=envelope.catalog_version,
            jurisdiction=payload.jurisdiction,
            verified_on=payload.verified_on,
            sources=tuple(LegalSource(**item.model_dump()) for item in payload.sources),
            rules=tuple(
                TaxRateRule(
                    **{
                        **item.model_dump(exclude={"components"}),
                        "components": tuple(
                            TaxRateComponent(**component.model_dump())
                            for component in item.components
                        ),
                    }
                )
                for item in payload.rules
            ),
        )
        obligation_catalog = self._obligation_repository.load_georgia()
        known_instruments = frozenset(
            item.instrument_id for item in obligation_catalog.entries
        )
        try:
            validated = validate_tax_rate_catalog(
                catalog,
                known_instrument_ids=known_instruments,
            )
            _validate_obligation_links(validated, obligation_catalog)
            return validated
        except ValueError as error:
            raise TaxRateCatalogError(str(error)) from error

    def _read_text(self, filename: str) -> str:
        if self._resource_directory is not None:
            return (self._resource_directory / filename).read_text(encoding="utf-8")
        catalog_files = resources.files("finradar.regulatory.catalogs")
        return catalog_files.joinpath(filename).read_text(encoding="utf-8")


def _payload_hash(payload: object) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _validate_obligation_links(
    rate_catalog: TaxRateCatalog,
    obligation_catalog: MandatoryObligationCatalog,
) -> None:
    entries = {
        item.instrument_id: item
        for item in obligation_catalog.entries
    }
    for rule in rate_catalog.rules:
        obligation = entries[rule.instrument_id]
        if rule.rule_id not in obligation.rate_rule_ids:
            raise ValueError(
                f"Tax-rate rule {rule.rule_id} is not linked from "
                f"instrument {rule.instrument_id}."
            )
