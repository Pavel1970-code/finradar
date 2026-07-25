from __future__ import annotations

import hashlib
import json
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from finradar.domain.tax_profile import (
    CompanyTaxProfile,
    FactSource,
    TaxProfileAnswer,
    VerificationStatus,
    assess_tax_profile,
)
from finradar.infrastructure.models import TaxProfileVersion
from finradar.infrastructure.tax_questionnaire_repository import (
    TaxQuestionnaireRepository,
)


TAX_PROFILE_SCHEMA_VERSION = 1


class TaxProfileRepositoryError(ValueError):
    """Raised when a stored company tax profile is invalid or corrupted."""


class _ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _AnswerData(_ContractModel):
    question_id: str
    fact_id: str
    values: tuple[str, ...]
    effective_from: date
    effective_through: date | None = None
    source: FactSource
    verification_status: VerificationStatus
    answered_at: datetime
    source_reference: str = ""


class _ProfileData(_ContractModel):
    schema_version: int
    company_external_id: str
    profile_version: int = Field(ge=1)
    valid_from: date
    questionnaire_version: int = Field(ge=1)
    answers: tuple[_AnswerData, ...]
    created_at: datetime


class SqlAlchemyTaxProfileRepository:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        questionnaire_repository: TaxQuestionnaireRepository | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._questionnaire_repository = (
            questionnaire_repository or TaxQuestionnaireRepository()
        )

    def record(self, profile: CompanyTaxProfile) -> str:
        questionnaire = self._questionnaire_repository.load_georgia(
            version=profile.questionnaire_version
        )
        assess_tax_profile(
            profile,
            questionnaire,
            on_date=profile.valid_from,
        )
        content_json = encode_tax_profile(profile)
        stored = TaxProfileVersion(
            company_external_id=profile.company_external_id,
            profile_version=profile.profile_version,
            valid_from=profile.valid_from,
            questionnaire_version=profile.questionnaire_version,
            content_json=content_json,
            content_hash=_content_hash(content_json),
            created_at=profile.created_at,
        )
        try:
            with self._session_factory() as session:
                session.add(stored)
                session.commit()
                return stored.id
        except IntegrityError as error:
            raise TaxProfileRepositoryError(
                "This company tax-profile version already exists."
            ) from error

    def load_latest(
        self,
        company_external_id: str,
        *,
        on_date: date | None = None,
    ) -> CompanyTaxProfile | None:
        statement = select(TaxProfileVersion).where(
            TaxProfileVersion.company_external_id == company_external_id
        )
        if on_date is not None:
            statement = statement.where(TaxProfileVersion.valid_from <= on_date)
        statement = statement.order_by(
            TaxProfileVersion.valid_from.desc(),
            TaxProfileVersion.profile_version.desc(),
        )
        with self._session_factory() as session:
            stored = session.scalar(statement.limit(1))
            if stored is None:
                return None
            return self._decode_stored(stored)

    def load_version(
        self,
        company_external_id: str,
        profile_version: int,
    ) -> CompanyTaxProfile:
        with self._session_factory() as session:
            stored = session.scalar(
                select(TaxProfileVersion).where(
                    TaxProfileVersion.company_external_id == company_external_id,
                    TaxProfileVersion.profile_version == profile_version,
                )
            )
            if stored is None:
                raise LookupError("Company tax-profile version was not found.")
            return self._decode_stored(stored)

    def _decode_stored(self, stored: TaxProfileVersion) -> CompanyTaxProfile:
        if _content_hash(stored.content_json) != stored.content_hash:
            raise TaxProfileRepositoryError(
                "Company tax-profile integrity check failed."
            )
        profile = decode_tax_profile(stored.content_json)
        if (
            profile.company_external_id != stored.company_external_id
            or profile.profile_version != stored.profile_version
            or profile.valid_from != stored.valid_from
            or profile.questionnaire_version != stored.questionnaire_version
        ):
            raise TaxProfileRepositoryError(
                "Company tax-profile database metadata does not match its content."
            )
        questionnaire = self._questionnaire_repository.load_georgia(
            version=profile.questionnaire_version
        )
        try:
            assess_tax_profile(
                profile,
                questionnaire,
                on_date=profile.valid_from,
            )
        except ValueError as error:
            raise TaxProfileRepositoryError(str(error)) from error
        return profile


def encode_tax_profile(profile: CompanyTaxProfile) -> str:
    payload = {
        "schema_version": TAX_PROFILE_SCHEMA_VERSION,
        "company_external_id": profile.company_external_id,
        "profile_version": profile.profile_version,
        "valid_from": profile.valid_from.isoformat(),
        "questionnaire_version": profile.questionnaire_version,
        "answers": [
            {
                "question_id": item.question_id,
                "fact_id": item.fact_id,
                "values": list(item.values),
                "effective_from": item.effective_from.isoformat(),
                "effective_through": (
                    item.effective_through.isoformat()
                    if item.effective_through is not None
                    else None
                ),
                "source": item.source.value,
                "verification_status": item.verification_status.value,
                "answered_at": item.answered_at.isoformat(),
                "source_reference": item.source_reference,
            }
            for item in sorted(
                profile.answers,
                key=lambda answer: (
                    answer.fact_id,
                    answer.effective_from,
                    answer.question_id,
                ),
            )
        ],
        "created_at": profile.created_at.isoformat(),
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def decode_tax_profile(content_json: str) -> CompanyTaxProfile:
    try:
        raw = json.loads(content_json)
        payload = _ProfileData.model_validate(raw)
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        raise TaxProfileRepositoryError(
            "Company tax-profile contract is invalid."
        ) from error
    if payload.schema_version != TAX_PROFILE_SCHEMA_VERSION:
        raise TaxProfileRepositoryError(
            "Unsupported company tax-profile schema version."
        )
    return CompanyTaxProfile(
        company_external_id=payload.company_external_id,
        profile_version=payload.profile_version,
        valid_from=payload.valid_from,
        questionnaire_version=payload.questionnaire_version,
        answers=tuple(
            TaxProfileAnswer(**item.model_dump()) for item in payload.answers
        ),
        created_at=payload.created_at,
    )


def _content_hash(content_json: str) -> str:
    return hashlib.sha256(content_json.encode("utf-8")).hexdigest()
