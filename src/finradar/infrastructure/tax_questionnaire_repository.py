from __future__ import annotations

import hashlib
import json
from datetime import date
from importlib import resources
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from finradar.domain.obligation_catalog import LegalSource
from finradar.domain.tax_profile import (
    AnswerKind,
    ConditionOperator,
    QuestionCondition,
    QuestionOption,
    TaxProfileQuestion,
    TaxQuestionnaireCatalog,
    validate_questionnaire_catalog,
)


TAX_QUESTIONNAIRE_SCHEMA_VERSION = 1


class TaxQuestionnaireError(ValueError):
    """Raised when a bundled tax-profile questionnaire is invalid."""


class _ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _SourceData(_ContractModel):
    source_id: str
    title: str
    url: str
    provisions: tuple[str, ...] = ()
    note: str = ""


class _OptionData(_ContractModel):
    value: str
    label_ru: str


class _ConditionData(_ContractModel):
    fact_id: str
    operator: ConditionOperator
    values: tuple[str, ...] = ()


class _QuestionData(_ContractModel):
    question_id: str
    fact_id: str
    order: int = Field(ge=1)
    text_ru: str
    help_ru: str
    answer_kind: AnswerKind
    required: bool
    options: tuple[_OptionData, ...] = ()
    show_when: tuple[_ConditionData, ...] = ()
    source_ids: tuple[str, ...]
    source_provisions: tuple[str, ...]
    source_reference_required_for: tuple[str, ...] = ()
    maximum_length: int | None = Field(default=None, ge=1, le=500)


class _QuestionnairePayload(_ContractModel):
    jurisdiction: str
    verified_on: date
    sources: tuple[_SourceData, ...]
    questions: tuple[_QuestionData, ...]


class _QuestionnaireEnvelope(_ContractModel):
    schema_version: int
    catalog_id: str
    catalog_version: int = Field(ge=1)
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    payload: _QuestionnairePayload


class TaxQuestionnaireRepository:
    def __init__(self, resource_directory: Path | None = None) -> None:
        self._resource_directory = resource_directory

    def load_georgia(self, *, version: int = 1) -> TaxQuestionnaireCatalog:
        filename = f"georgia_tax_questionnaire_v{version}.json"
        try:
            content = self._read_text(filename)
        except FileNotFoundError as error:
            raise TaxQuestionnaireError(
                f"Unknown Georgian tax questionnaire version: {version}."
            ) from error
        try:
            raw = json.loads(content)
            envelope = _QuestionnaireEnvelope.model_validate(raw)
        except (json.JSONDecodeError, TypeError, ValueError) as error:
            raise TaxQuestionnaireError(
                "Tax questionnaire contract is invalid."
            ) from error
        if envelope.schema_version != TAX_QUESTIONNAIRE_SCHEMA_VERSION:
            raise TaxQuestionnaireError("Unsupported tax questionnaire schema.")
        if envelope.catalog_id != "georgia-tax-profile-questionnaire":
            raise TaxQuestionnaireError("Tax questionnaire catalog ID is invalid.")
        if envelope.catalog_version != version:
            raise TaxQuestionnaireError(
                "Tax questionnaire version does not match its filename."
            )
        if _payload_hash(raw.get("payload")) != envelope.payload_sha256:
            raise TaxQuestionnaireError(
                "Tax questionnaire integrity check failed."
            )

        payload = envelope.payload
        catalog = TaxQuestionnaireCatalog(
            catalog_id=envelope.catalog_id,
            version=envelope.catalog_version,
            jurisdiction=payload.jurisdiction,
            verified_on=payload.verified_on,
            sources=tuple(LegalSource(**item.model_dump()) for item in payload.sources),
            questions=tuple(
                TaxProfileQuestion(
                    **{
                        **item.model_dump(exclude={"options", "show_when"}),
                        "options": tuple(
                            QuestionOption(**option.model_dump())
                            for option in item.options
                        ),
                        "show_when": tuple(
                            QuestionCondition(**condition.model_dump())
                            for condition in item.show_when
                        ),
                    }
                )
                for item in payload.questions
            ),
        )
        try:
            return validate_questionnaire_catalog(catalog)
        except ValueError as error:
            raise TaxQuestionnaireError(str(error)) from error

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
