from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Protocol

from finradar.domain.financial_snapshot import DatasetKind, FinancialSnapshot
from finradar.domain.tax_profile import (
    CompanyTaxProfile,
    FactSource,
    TaxProfileAnswer,
    TaxProfileAssessment,
    TaxProfileReadiness,
    TaxQuestionnaireCatalog,
    VerificationStatus,
    assess_tax_profile,
)
from finradar.infrastructure.tax_questionnaire_repository import (
    TaxQuestionnaireRepository,
)


class TaxProfileStore(Protocol):
    def record(self, profile: CompanyTaxProfile) -> str: ...

    def load_latest(
        self,
        company_external_id: str,
        *,
        on_date: date | None = None,
    ) -> CompanyTaxProfile | None: ...


@dataclass(frozen=True, slots=True)
class TaxProfileDraftAnswer:
    question_id: str
    values: tuple[str, ...]
    source: FactSource = FactSource.USER_CONFIRMATION
    verification_status: VerificationStatus = VerificationStatus.USER_CONFIRMED
    source_reference: str = ""


@dataclass(frozen=True, slots=True)
class TaxProfileSuggestion:
    question_id: str
    values: tuple[str, ...]
    source_reference: str


@dataclass(frozen=True, slots=True)
class TaxProfileSetupContext:
    company_external_id: str
    company_name: str
    effective_date: date
    suggestions: tuple[TaxProfileSuggestion, ...] = ()


@dataclass(frozen=True, slots=True)
class TaxProfileSetupState:
    context: TaxProfileSetupContext
    catalog: TaxQuestionnaireCatalog
    answers: tuple[TaxProfileDraftAnswer, ...]
    assessment: TaxProfileAssessment
    latest_profile: CompanyTaxProfile | None
    suggested_question_ids: frozenset[str]


@dataclass(frozen=True, slots=True)
class SavedTaxProfile:
    profile: CompanyTaxProfile
    assessment: TaxProfileAssessment
    created_new_version: bool


class TaxProfileSetupService:
    """Builds and stores local, immutable company tax-profile versions."""

    def __init__(
        self,
        store: TaxProfileStore,
        *,
        questionnaire_repository: TaxQuestionnaireRepository | None = None,
    ) -> None:
        self._store = store
        self._questionnaire_repository = (
            questionnaire_repository or TaxQuestionnaireRepository()
        )

    def load(self, context: TaxProfileSetupContext) -> TaxProfileSetupState:
        catalog = self._questionnaire_repository.load_georgia()
        latest = self._store.load_latest(
            context.company_external_id,
            on_date=context.effective_date,
        )
        answers: dict[str, TaxProfileDraftAnswer] = {}
        if latest is not None:
            for answer in latest.answers:
                if answer.applies_on(context.effective_date):
                    answers[answer.question_id] = TaxProfileDraftAnswer(
                        question_id=answer.question_id,
                        values=answer.values,
                        source=answer.source,
                        verification_status=answer.verification_status,
                        source_reference=answer.source_reference,
                    )

        suggested_ids: set[str] = set()
        for suggestion in context.suggestions:
            if suggestion.question_id in answers:
                continue
            question = catalog.question(suggestion.question_id)
            answers[suggestion.question_id] = TaxProfileDraftAnswer(
                question_id=question.question_id,
                values=suggestion.values,
                source=FactSource.ACCOUNTING_CONNECTOR,
                verification_status=VerificationStatus.UNVERIFIED,
                source_reference=suggestion.source_reference,
            )
            suggested_ids.add(question.question_id)

        ordered = self._ordered_answers(catalog, answers.values())
        assessment = self.assess(
            context,
            ordered,
            profile_version=latest.profile_version if latest is not None else 1,
        )
        return TaxProfileSetupState(
            context=context,
            catalog=catalog,
            answers=ordered,
            assessment=assessment,
            latest_profile=latest,
            suggested_question_ids=frozenset(suggested_ids),
        )

    def assess(
        self,
        context: TaxProfileSetupContext,
        answers: tuple[TaxProfileDraftAnswer, ...],
        *,
        profile_version: int = 1,
    ) -> TaxProfileAssessment:
        catalog = self._questionnaire_repository.load_georgia()
        profile = self._build_profile(
            context,
            catalog,
            answers,
            profile_version=profile_version,
            created_at=datetime.now(timezone.utc),
        )
        return assess_tax_profile(profile, catalog, on_date=context.effective_date)

    def save(
        self,
        context: TaxProfileSetupContext,
        answers: tuple[TaxProfileDraftAnswer, ...],
    ) -> SavedTaxProfile:
        catalog = self._questionnaire_repository.load_georgia()
        latest_overall = self._store.load_latest(context.company_external_id)
        if (
            latest_overall is not None
            and context.effective_date < latest_overall.valid_from
        ):
            raise ValueError(
                "Нельзя сохранить профиль задним числом после более новой версии."
            )

        draft_assessment = self.assess(
            context,
            answers,
            profile_version=(
                latest_overall.profile_version + 1
                if latest_overall is not None
                else 1
            ),
        )
        visible_ids = {
            question.question_id for question in draft_assessment.visible_questions
        }
        normalized = self._ordered_answers(
            catalog,
            (item for item in answers if item.question_id in visible_ids),
        )

        normalized_assessment = self.assess(
            context,
            normalized,
            profile_version=(
                latest_overall.profile_version + 1
                if latest_overall is not None
                else 1
            ),
        )
        if normalized_assessment.readiness is TaxProfileReadiness.CONFLICT:
            messages = "; ".join(
                finding.message_ru
                for finding in normalized_assessment.findings
                if finding.severity.value == "error"
            )
            raise ValueError(messages or "Налоговый профиль содержит противоречия.")

        if latest_overall is not None and self._same_active_answers(
            latest_overall,
            normalized,
            on_date=context.effective_date,
        ):
            return SavedTaxProfile(
                profile=latest_overall,
                assessment=assess_tax_profile(
                    latest_overall,
                    catalog,
                    on_date=context.effective_date,
                ),
                created_new_version=False,
            )

        profile = self._build_profile(
            context,
            catalog,
            normalized,
            profile_version=(
                latest_overall.profile_version + 1
                if latest_overall is not None
                else 1
            ),
            created_at=datetime.now(timezone.utc),
        )
        assessment = assess_tax_profile(
            profile,
            catalog,
            on_date=context.effective_date,
        )
        self._store.record(profile)
        return SavedTaxProfile(
            profile=profile,
            assessment=assessment,
            created_new_version=True,
        )

    @staticmethod
    def _build_profile(
        context: TaxProfileSetupContext,
        catalog: TaxQuestionnaireCatalog,
        answers: tuple[TaxProfileDraftAnswer, ...],
        *,
        profile_version: int,
        created_at: datetime,
    ) -> CompanyTaxProfile:
        return CompanyTaxProfile(
            company_external_id=context.company_external_id,
            profile_version=profile_version,
            valid_from=context.effective_date,
            questionnaire_version=catalog.version,
            answers=tuple(
                TaxProfileAnswer(
                    question_id=item.question_id,
                    fact_id=catalog.question(item.question_id).fact_id,
                    values=item.values,
                    effective_from=context.effective_date,
                    effective_through=None,
                    source=item.source,
                    verification_status=item.verification_status,
                    answered_at=created_at,
                    source_reference=item.source_reference.strip(),
                )
                for item in answers
            ),
            created_at=created_at,
        )

    @staticmethod
    def _ordered_answers(
        catalog: TaxQuestionnaireCatalog,
        answers,
    ) -> tuple[TaxProfileDraftAnswer, ...]:
        by_question = {item.question_id: item for item in answers}
        return tuple(
            by_question[question.question_id]
            for question in sorted(catalog.questions, key=lambda item: item.order)
            if question.question_id in by_question
        )

    @staticmethod
    def _same_active_answers(
        profile: CompanyTaxProfile,
        draft_answers: tuple[TaxProfileDraftAnswer, ...],
        *,
        on_date: date,
    ) -> bool:
        stored = {
            item.question_id: (
                item.values,
                item.source,
                item.verification_status,
                item.source_reference,
            )
            for item in profile.answers
            if item.applies_on(on_date)
        }
        draft = {
            item.question_id: (
                item.values,
                item.source,
                item.verification_status,
                item.source_reference.strip(),
            )
            for item in draft_answers
        }
        return stored == draft


def tax_profile_context_from_snapshot(
    snapshot: FinancialSnapshot,
    *,
    effective_date: date,
) -> TaxProfileSetupContext:
    if snapshot.company is None:
        raise ValueError("В учётных данных отсутствует карточка компании.")
    company = snapshot.company
    if company.jurisdiction != "GE":
        raise ValueError(
            "Налоговый профиль Грузии доступен только для компании с юрисдикцией GE."
        )
    suggestions: list[TaxProfileSuggestion] = []
    source_reference = snapshot.source_system

    if company.tax_regime == "ge-vat-registered-domestic-standard-only":
        suggestions.extend(
            (
                TaxProfileSuggestion(
                    question_id="company-tax-residency",
                    values=("georgian_enterprise",),
                    source_reference=source_reference,
                ),
                TaxProfileSuggestion(
                    question_id="vat-registration",
                    values=("yes",),
                    source_reference=source_reference,
                ),
            )
        )
    if snapshot.supplies(DatasetKind.PAYROLL) and snapshot.payroll_records:
        suggestions.append(
            TaxProfileSuggestion(
                question_id="company-has-employees",
                values=("yes",),
                source_reference=source_reference,
            )
        )
    return TaxProfileSetupContext(
        company_external_id=company.external_id,
        company_name=company.name,
        effective_date=effective_date,
        suggestions=tuple(suggestions),
    )
