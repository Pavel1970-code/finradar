from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import Enum

from finradar.domain.obligation_catalog import LegalSource


class AnswerKind(str, Enum):
    SINGLE_CHOICE = "single_choice"
    MULTIPLE_CHOICE = "multiple_choice"
    DATE = "date"
    DECIMAL = "decimal"
    TEXT = "text"


class ConditionOperator(str, Enum):
    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    ANY_OF = "any_of"
    CONTAINS = "contains"
    PRESENT = "present"


class FactSource(str, Enum):
    ACCOUNTING_CONNECTOR = "accounting_connector"
    PUBLIC_REGISTRY = "public_registry"
    DOCUMENT = "document"
    USER_CONFIRMATION = "user_confirmation"
    SYSTEM_DERIVED = "system_derived"


class VerificationStatus(str, Enum):
    VERIFIED = "verified"
    USER_CONFIRMED = "user_confirmed"
    UNVERIFIED = "unverified"


class ProfileFindingSeverity(str, Enum):
    WARNING = "warning"
    ERROR = "error"


class TaxProfileReadiness(str, Enum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    CONFLICT = "conflict"


@dataclass(frozen=True, slots=True)
class QuestionOption:
    value: str
    label_ru: str


@dataclass(frozen=True, slots=True)
class QuestionCondition:
    fact_id: str
    operator: ConditionOperator
    values: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TaxProfileQuestion:
    question_id: str
    fact_id: str
    order: int
    text_ru: str
    help_ru: str
    answer_kind: AnswerKind
    required: bool
    options: tuple[QuestionOption, ...]
    show_when: tuple[QuestionCondition, ...]
    source_ids: tuple[str, ...]
    source_provisions: tuple[str, ...]
    source_reference_required_for: tuple[str, ...] = ()
    maximum_length: int | None = None


@dataclass(frozen=True, slots=True)
class TaxQuestionnaireCatalog:
    catalog_id: str
    version: int
    jurisdiction: str
    verified_on: date
    sources: tuple[LegalSource, ...]
    questions: tuple[TaxProfileQuestion, ...]

    def question(self, question_id: str) -> TaxProfileQuestion:
        for item in self.questions:
            if item.question_id == question_id:
                return item
        raise LookupError(f"Unknown tax-profile question: {question_id}.")


@dataclass(frozen=True, slots=True)
class TaxProfileAnswer:
    question_id: str
    fact_id: str
    values: tuple[str, ...]
    effective_from: date
    effective_through: date | None
    source: FactSource
    verification_status: VerificationStatus
    answered_at: datetime
    source_reference: str = ""

    @property
    def is_unknown(self) -> bool:
        return self.values == ("unknown",)

    def applies_on(self, target_date: date) -> bool:
        return self.effective_from <= target_date and (
            self.effective_through is None
            or target_date <= self.effective_through
        )


@dataclass(frozen=True, slots=True)
class CompanyTaxProfile:
    company_external_id: str
    profile_version: int
    valid_from: date
    questionnaire_version: int
    answers: tuple[TaxProfileAnswer, ...]
    created_at: datetime

    def answer_by_question(
        self,
        question_id: str,
        *,
        on_date: date | None = None,
    ) -> TaxProfileAnswer | None:
        matches = tuple(
            item
            for item in self.answers
            if item.question_id == question_id
            and (on_date is None or item.applies_on(on_date))
        )
        if len(matches) > 1:
            raise ValueError(
                f"Tax profile has multiple answers for {question_id} on one date."
            )
        return matches[0] if matches else None

    def answer_by_fact(
        self,
        fact_id: str,
        *,
        on_date: date | None = None,
    ) -> TaxProfileAnswer | None:
        matches = tuple(
            item
            for item in self.answers
            if item.fact_id == fact_id
            and (on_date is None or item.applies_on(on_date))
        )
        if len(matches) > 1:
            raise ValueError(
                f"Tax profile has multiple answers for {fact_id} on one date."
            )
        return matches[0] if matches else None

    def available_fact_ids(self, *, on_date: date) -> frozenset[str]:
        return frozenset(
            item.fact_id
            for item in self.answers
            if item.applies_on(on_date) and not item.is_unknown
        )

    def fact_values(self, *, on_date: date) -> dict[str, tuple[str, ...]]:
        return {
            item.fact_id: item.values
            for item in self.answers
            if item.applies_on(on_date) and not item.is_unknown
        }


@dataclass(frozen=True, slots=True)
class TaxProfileFinding:
    code: str
    severity: ProfileFindingSeverity
    message_ru: str
    fact_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TaxProfileAssessment:
    readiness: TaxProfileReadiness
    visible_questions: tuple[TaxProfileQuestion, ...]
    unanswered_required_questions: tuple[TaxProfileQuestion, ...]
    findings: tuple[TaxProfileFinding, ...]


def validate_questionnaire_catalog(
    catalog: TaxQuestionnaireCatalog,
) -> TaxQuestionnaireCatalog:
    if catalog.version < 1:
        raise ValueError("Questionnaire catalog version must be positive.")
    if catalog.jurisdiction != "GE":
        raise ValueError("This questionnaire currently supports Georgia only.")
    source_ids = tuple(item.source_id for item in catalog.sources)
    if not source_ids or len(source_ids) != len(set(source_ids)):
        raise ValueError("Questionnaire source identifiers are invalid.")

    question_ids = tuple(item.question_id for item in catalog.questions)
    if len(question_ids) != len(set(question_ids)):
        raise ValueError("Questionnaire question identifiers must be unique.")
    fact_ids = tuple(item.fact_id for item in catalog.questions)
    if len(fact_ids) != len(set(fact_ids)):
        raise ValueError("Questionnaire fact identifiers must be unique.")
    orders = tuple(item.order for item in catalog.questions)
    if len(orders) != len(set(orders)) or any(item < 1 for item in orders):
        raise ValueError("Questionnaire order values must be unique and positive.")

    known_facts = set(fact_ids)
    fact_orders = {item.fact_id: item.order for item in catalog.questions}
    known_sources = set(source_ids)
    for question in catalog.questions:
        if not question.text_ru.strip() or not question.help_ru.strip():
            raise ValueError(f"Question {question.question_id} has no user text.")
        if not question.source_ids or not set(question.source_ids) <= known_sources:
            raise ValueError(f"Question {question.question_id} has invalid sources.")
        if not question.source_provisions:
            raise ValueError(
                f"Question {question.question_id} has no legal provisions."
            )
        option_values = tuple(item.value for item in question.options)
        if len(option_values) != len(set(option_values)):
            raise ValueError(f"Question {question.question_id} has duplicate options.")
        if question.answer_kind in {
            AnswerKind.SINGLE_CHOICE,
            AnswerKind.MULTIPLE_CHOICE,
        } and not question.options:
            raise ValueError(f"Question {question.question_id} needs options.")
        if (
            question.required
            and question.answer_kind
            in {AnswerKind.SINGLE_CHOICE, AnswerKind.MULTIPLE_CHOICE}
            and "unknown" not in option_values
        ):
            raise ValueError(
                f"Required question {question.question_id} needs an unknown option."
            )
        if question.answer_kind not in {
            AnswerKind.SINGLE_CHOICE,
            AnswerKind.MULTIPLE_CHOICE,
        } and question.options:
            raise ValueError(
                f"Question {question.question_id} cannot have choice options."
            )
        if not set(question.source_reference_required_for) <= set(option_values):
            raise ValueError(
                f"Question {question.question_id} has invalid evidence requirements."
            )
        for condition in question.show_when:
            if condition.fact_id not in known_facts:
                raise ValueError(
                    f"Question {question.question_id} has an unknown dependency."
                )
            if condition.fact_id == question.fact_id:
                raise ValueError(
                    f"Question {question.question_id} cannot depend on itself."
                )
            if fact_orders[condition.fact_id] >= question.order:
                raise ValueError(
                    f"Question {question.question_id} depends on a later question."
                )
            if (
                condition.operator is not ConditionOperator.PRESENT
                and not condition.values
            ):
                raise ValueError(
                    f"Question {question.question_id} has an empty condition."
                )
    return catalog


def validate_answer(
    answer: TaxProfileAnswer,
    question: TaxProfileQuestion,
) -> TaxProfileAnswer:
    if answer.question_id != question.question_id:
        raise ValueError("Answer question ID does not match the definition.")
    if answer.fact_id != question.fact_id:
        raise ValueError("Answer fact ID does not match the definition.")
    if answer.effective_through is not None and (
        answer.effective_through < answer.effective_from
    ):
        raise ValueError("Answer effective period is invalid.")
    if (
        answer.answered_at.tzinfo is None
        or answer.answered_at.utcoffset() is None
    ):
        raise ValueError("Answer timestamp must include a timezone.")
    if not answer.values:
        raise ValueError("Answer must contain a value.")

    if question.answer_kind is AnswerKind.SINGLE_CHOICE:
        if len(answer.values) != 1:
            raise ValueError("Single-choice answer must contain exactly one value.")
        _validate_options(answer, question)
    elif question.answer_kind is AnswerKind.MULTIPLE_CHOICE:
        if len(answer.values) != len(set(answer.values)):
            raise ValueError("Multiple-choice answer contains duplicates.")
        _validate_options(answer, question)
        if "none" in answer.values and len(answer.values) != 1:
            raise ValueError("'none' cannot be combined with other choices.")
        if "unknown" in answer.values and len(answer.values) != 1:
            raise ValueError("'unknown' cannot be combined with other choices.")
    elif question.answer_kind is AnswerKind.DATE:
        if len(answer.values) != 1:
            raise ValueError("Date answer must contain exactly one value.")
        try:
            date.fromisoformat(answer.values[0])
        except ValueError as error:
            raise ValueError("Date answer must use ISO format.") from error
    elif question.answer_kind is AnswerKind.DECIMAL:
        if len(answer.values) != 1:
            raise ValueError("Decimal answer must contain exactly one value.")
        try:
            value = Decimal(answer.values[0])
        except InvalidOperation as error:
            raise ValueError("Decimal answer is invalid.") from error
        if not value.is_finite() or value < 0:
            raise ValueError("Decimal answer must be finite and non-negative.")
    elif question.answer_kind is AnswerKind.TEXT:
        if len(answer.values) != 1 or not answer.values[0].strip():
            raise ValueError("Text answer must contain non-empty text.")
        if (
            question.maximum_length is not None
            and len(answer.values[0]) > question.maximum_length
        ):
            raise ValueError("Text answer exceeds the configured maximum length.")
    return answer


def assess_tax_profile(
    profile: CompanyTaxProfile,
    catalog: TaxQuestionnaireCatalog,
    *,
    on_date: date,
) -> TaxProfileAssessment:
    if profile.profile_version < 1:
        raise ValueError("Tax profile version must be positive.")
    if profile.questionnaire_version != catalog.version:
        raise ValueError("Tax profile questionnaire version does not match.")
    if not profile.company_external_id.strip():
        raise ValueError("Tax profile company ID is required.")
    if (
        profile.created_at.tzinfo is None
        or profile.created_at.utcoffset() is None
    ):
        raise ValueError("Tax profile timestamp must include a timezone.")

    for answer in profile.answers:
        validate_answer(answer, catalog.question(answer.question_id))
    _validate_answer_periods(profile.answers)

    active_answers = {
        item.fact_id: item
        for item in profile.answers
        if item.applies_on(on_date)
    }
    visible = tuple(
        question
        for question in sorted(catalog.questions, key=lambda item: item.order)
        if _conditions_match(question.show_when, active_answers)
    )
    unanswered = tuple(
        question
        for question in visible
        if question.required
        and (
            question.fact_id not in active_answers
            or active_answers[question.fact_id].is_unknown
        )
    )
    findings = _profile_findings(
        profile,
        visible_questions=visible,
        active_answers=active_answers,
        on_date=on_date,
    )
    if any(item.severity is ProfileFindingSeverity.ERROR for item in findings):
        readiness = TaxProfileReadiness.CONFLICT
    elif unanswered:
        readiness = TaxProfileReadiness.INCOMPLETE
    else:
        readiness = TaxProfileReadiness.COMPLETE
    return TaxProfileAssessment(
        readiness=readiness,
        visible_questions=visible,
        unanswered_required_questions=unanswered,
        findings=findings,
    )


def derived_tax_profile_facts(
    profile: CompanyTaxProfile,
    *,
    on_date: date,
) -> dict[str, tuple[str, ...]]:
    facts = profile.fact_values(on_date=on_date)
    derived = dict(facts)

    legal_form = facts.get("legal_form")
    residency = facts.get("tax_residency_status")
    if legal_form is not None and residency is not None:
        if legal_form == ("individual_entrepreneur",):
            derived["entity_tax_status"] = ("individual_entrepreneur",)
            derived["recipient_tax_status"] = ("individual_entrepreneur",)
        elif residency == ("georgian_enterprise",):
            derived["entity_tax_status"] = ("resident_enterprise",)
        elif residency == ("foreign_enterprise",):
            derived["entity_tax_status"] = ("foreign_enterprise",)

    regime = facts.get("individual_special_regime")
    if regime is not None:
        regime_value = regime[0]
        derived["micro_business_status"] = (
            "active" if regime_value == "micro_business" else "inactive",
        )
        derived["small_business_status"] = (
            "active" if regime_value == "small_business" else "inactive",
        )
        derived["fixed_taxpayer_status"] = (
            "active" if regime_value == "fixed_taxpayer" else "inactive",
        )

    relief_status = facts.get("uses_tax_reliefs")
    if relief_status is not None:
        derived["applicable_reliefs"] = relief_status

    special_statuses = facts.get("company_special_statuses", ())
    for status in special_statuses:
        if status not in {"none", "unknown"}:
            derived[f"{status}_status"] = ("active",)
    return derived


def _validate_options(
    answer: TaxProfileAnswer,
    question: TaxProfileQuestion,
) -> None:
    allowed = {item.value for item in question.options}
    if not set(answer.values) <= allowed:
        raise ValueError(f"Answer to {question.question_id} has an invalid option.")


def _validate_answer_periods(answers: tuple[TaxProfileAnswer, ...]) -> None:
    by_fact: dict[str, list[TaxProfileAnswer]] = {}
    for answer in answers:
        by_fact.setdefault(answer.fact_id, []).append(answer)
    for fact_id, versions in by_fact.items():
        versions.sort(key=lambda item: item.effective_from)
        for previous, current in zip(versions, versions[1:]):
            if previous.effective_through is None:
                raise ValueError(
                    f"Tax-profile fact {fact_id} has an open historical answer."
                )
            if current.effective_from <= previous.effective_through:
                raise ValueError(
                    f"Tax-profile fact {fact_id} has overlapping answers."
                )


def _conditions_match(
    conditions: tuple[QuestionCondition, ...],
    answers: dict[str, TaxProfileAnswer],
) -> bool:
    for condition in conditions:
        answer = answers.get(condition.fact_id)
        if condition.operator is ConditionOperator.PRESENT:
            if answer is None or answer.is_unknown:
                return False
        elif answer is None:
            return False
        elif condition.operator is ConditionOperator.EQUALS:
            if answer.values != condition.values:
                return False
        elif condition.operator is ConditionOperator.NOT_EQUALS:
            if answer.values == condition.values:
                return False
        elif condition.operator is ConditionOperator.ANY_OF:
            if not set(answer.values) & set(condition.values):
                return False
        elif condition.operator is ConditionOperator.CONTAINS:
            if not set(condition.values) <= set(answer.values):
                return False
    return True


def _profile_findings(
    profile: CompanyTaxProfile,
    *,
    visible_questions: tuple[TaxProfileQuestion, ...],
    active_answers: dict[str, TaxProfileAnswer],
    on_date: date,
) -> tuple[TaxProfileFinding, ...]:
    findings: list[TaxProfileFinding] = []
    visible_fact_ids = {item.fact_id for item in visible_questions}
    for question in visible_questions:
        answer = active_answers.get(question.fact_id)
        if (
            answer is not None
            and not answer.is_unknown
            and answer.verification_status is VerificationStatus.UNVERIFIED
        ):
            findings.append(
                TaxProfileFinding(
                    code="tax_profile_unverified_fact",
                    severity=ProfileFindingSeverity.WARNING,
                    message_ru=(
                        f"Требуется подтвердить автоматически полученный ответ: "
                        f"{question.text_ru}"
                    ),
                    fact_ids=(question.fact_id,),
                )
            )
        if (
            answer is not None
            and set(answer.values) & set(question.source_reference_required_for)
            and not answer.source_reference.strip()
        ):
            findings.append(
                TaxProfileFinding(
                    code="tax_profile_evidence_missing",
                    severity=ProfileFindingSeverity.WARNING,
                    message_ru=(
                        f"Для ответа «{question.text_ru}» не указан "
                        "подтверждающий документ или источник."
                    ),
                    fact_ids=(question.fact_id,),
                )
            )

    hidden_answers = tuple(
        item
        for item in profile.answers
        if item.fact_id not in visible_fact_ids
        and item.applies_on(on_date)
    )
    if hidden_answers:
        findings.append(
            TaxProfileFinding(
                code="tax_profile_hidden_answer",
                severity=ProfileFindingSeverity.WARNING,
                message_ru=(
                    "Профиль содержит ответы на вопросы, которые не применимы "
                    "при текущей конфигурации."
                ),
                fact_ids=tuple(item.fact_id for item in hidden_answers),
            )
        )

    legal_form = _single_value(active_answers, "legal_form")
    individual_regime = _single_value(active_answers, "individual_special_regime")
    special_statuses = _values(active_answers, "company_special_statuses")
    has_employees = _single_value(active_answers, "has_employees")
    vat_status = _single_value(active_answers, "vat_registration_status")

    if legal_form == "individual_entrepreneur" and special_statuses not in {
        (),
        ("none",),
        ("unknown",),
    }:
        findings.append(
            TaxProfileFinding(
                code="individual_company_status_conflict",
                severity=ProfileFindingSeverity.ERROR,
                message_ru=(
                    "Статус предприятия-юридического лица нельзя назначить "
                    "индивидуальному предпринимателю."
                ),
                fact_ids=("legal_form", "company_special_statuses"),
            )
        )
    if "international_company" in special_statuses and (
        "free_industrial_zone_enterprise" in special_statuses
    ):
        findings.append(
            TaxProfileFinding(
                code="international_fiz_status_conflict",
                severity=ProfileFindingSeverity.ERROR,
                message_ru=(
                    "Международная компания не может одновременно быть "
                    "предприятием свободной индустриальной зоны."
                ),
                fact_ids=("company_special_statuses",),
            )
        )
    if individual_regime == "micro_business" and has_employees == "yes":
        findings.append(
            TaxProfileFinding(
                code="micro_business_employee_conflict",
                severity=ProfileFindingSeverity.ERROR,
                message_ru=(
                    "Статус микробизнеса противоречит наличию наёмных работников."
                ),
                fact_ids=("individual_special_regime", "has_employees"),
            )
        )
    if individual_regime == "fixed_taxpayer" and vat_status == "yes":
        findings.append(
            TaxProfileFinding(
                code="fixed_taxpayer_vat_conflict",
                severity=ProfileFindingSeverity.ERROR,
                message_ru=(
                    "Статус фиксированного налогоплательщика противоречит "
                    "регистрации плательщиком НДС."
                ),
                fact_ids=("individual_special_regime", "vat_registration_status"),
            )
        )
    return tuple(findings)


def _single_value(
    answers: dict[str, TaxProfileAnswer],
    fact_id: str,
) -> str | None:
    answer = answers.get(fact_id)
    if answer is None or len(answer.values) != 1:
        return None
    return answer.values[0]


def _values(
    answers: dict[str, TaxProfileAnswer],
    fact_id: str,
) -> tuple[str, ...]:
    answer = answers.get(fact_id)
    return answer.values if answer is not None else ()
