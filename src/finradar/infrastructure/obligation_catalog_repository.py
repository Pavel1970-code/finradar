import hashlib
import json
from datetime import date
from importlib import resources
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from finradar.domain.obligation_catalog import (
    ApplicabilityScope,
    CashFlowTreatment,
    CatalogFinding,
    FormulaStatus,
    LegalSource,
    MandatoryObligation,
    MandatoryObligationCatalog,
    ObligationKind,
    validate_obligation_catalog,
)


CATALOG_SCHEMA_VERSION = 1


class ObligationCatalogError(ValueError):
    """Raised when a bundled obligation catalog is invalid or corrupted."""


class _ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _SourceData(_ContractModel):
    source_id: str
    title: str
    url: str
    provisions: tuple[str, ...] = ()
    note: str = ""


class _EntryData(_ContractModel):
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


class _FindingData(_ContractModel):
    finding_id: str
    statement: str
    source_ids: tuple[str, ...]
    consequence: str


class _CatalogPayload(_ContractModel):
    jurisdiction: str
    verified_on: date
    rates_included: bool
    sources: tuple[_SourceData, ...]
    entries: tuple[_EntryData, ...]
    findings: tuple[_FindingData, ...] = ()


class _CatalogEnvelope(_ContractModel):
    schema_version: int
    catalog_id: str
    catalog_version: int = Field(ge=1)
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    payload: _CatalogPayload


class ObligationCatalogRepository:
    def __init__(self, resource_directory: Path | None = None) -> None:
        self._resource_directory = resource_directory

    def load_georgia(self, *, version: int = 1) -> MandatoryObligationCatalog:
        filename = f"georgia_mandatory_obligations_v{version}.json"
        try:
            content = self._read_text(filename)
        except FileNotFoundError as error:
            raise ObligationCatalogError(
                f"Unknown Georgian obligation catalog version: {version}."
            ) from error
        try:
            raw = json.loads(content)
            envelope = _CatalogEnvelope.model_validate(raw)
        except (json.JSONDecodeError, TypeError, ValueError) as error:
            raise ObligationCatalogError(
                "Mandatory-obligation catalog contract is invalid."
            ) from error
        if envelope.schema_version != CATALOG_SCHEMA_VERSION:
            raise ObligationCatalogError(
                "Unsupported mandatory-obligation catalog schema."
            )
        if envelope.catalog_id != "georgia-mandatory-obligations":
            raise ObligationCatalogError("Mandatory-obligation catalog ID is invalid.")
        if envelope.catalog_version != version:
            raise ObligationCatalogError(
                "Mandatory-obligation catalog version does not match its filename."
            )
        if _payload_hash(raw.get("payload")) != envelope.payload_sha256:
            raise ObligationCatalogError(
                "Mandatory-obligation catalog integrity check failed."
            )
        payload = envelope.payload
        catalog = MandatoryObligationCatalog(
            catalog_id=envelope.catalog_id,
            version=envelope.catalog_version,
            jurisdiction=payload.jurisdiction,
            verified_on=payload.verified_on,
            rates_included=payload.rates_included,
            sources=tuple(LegalSource(**item.model_dump()) for item in payload.sources),
            entries=tuple(
                MandatoryObligation(**item.model_dump()) for item in payload.entries
            ),
            findings=tuple(
                CatalogFinding(**item.model_dump()) for item in payload.findings
            ),
        )
        try:
            return validate_obligation_catalog(catalog)
        except ValueError as error:
            raise ObligationCatalogError(str(error)) from error

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
