import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from finradar.application.tax_profile_readiness import assess_tax_rule_facts
from finradar.domain.tax_profile import (
    CompanyTaxProfile,
    FactSource,
    ProfileFindingSeverity,
    TaxProfileAnswer,
    TaxProfileReadiness,
    VerificationStatus,
    assess_tax_profile,
)
from finradar.infrastructure.database import Base, migrate_database
from finradar.infrastructure.tax_profile_repository import (
    SqlAlchemyTaxProfileRepository,
    TaxProfileRepositoryError,
)
from finradar.infrastructure.tax_questionnaire_repository import (
    TaxQuestionnaireError,
    TaxQuestionnaireRepository,
)
from finradar.infrastructure.tax_rate_catalog_repository import (
    TaxRateCatalogRepository,
)


QUESTIONNAIRE_PATH = (
    Path(__file__).parents[1]
    / "src"
    / "finradar"
    / "regulatory"
    / "catalogs"
    / "georgia_tax_questionnaire_v1.json"
)
NOW = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)


def answer(
    question_id: str,
    fact_id: str,
    *values: str,
    source_reference: str = "",
) -> TaxProfileAnswer:
    return TaxProfileAnswer(
        question_id=question_id,
        fact_id=fact_id,
        values=values,
        effective_from=date(2026, 7, 25),
        effective_through=None,
        source=FactSource.USER_CONFIRMATION,
        verification_status=VerificationStatus.USER_CONFIRMED,
        answered_at=NOW,
        source_reference=source_reference,
    )


def complete_company_profile(
    *,
    profile_version: int = 1,
    special_statuses: tuple[str, ...] = ("none",),
) -> CompanyTaxProfile:
    answers = (
        answer(
            "company-legal-form",
            "legal_form",
            "limited_liability_company",
        ),
        answer(
            "company-tax-residency",
            "tax_residency_status",
            "georgian_enterprise",
        ),
        answer("company-primary-activity", "activity_type", "retail_trade"),
        answer("company-municipality", "municipality_code", "tbilisi"),
        answer(
            "company-special-statuses",
            "company_special_statuses",
            *special_statuses,
            source_reference=(
                "registry:international"
                if special_statuses != ("none",)
                else ""
            ),
        ),
        answer("regulated-activity-types", "regulated_activity_types", "none"),
        answer("vat-registration", "vat_registration_status", "no"),
        answer("company-has-employees", "has_employees", "no"),
        answer("company-imports-goods", "has_import_activity", "no"),
        answer("company-excise-activity", "has_excise_activity", "no"),
        answer("company-taxable-property", "has_taxable_property", "no"),
        answer("company-land", "has_land", "no"),
        answer("company-pays-dividends", "pays_dividends", "no"),
        answer("company-pays-interest", "pays_interest", "no"),
        answer("company-pays-nonresidents", "pays_nonresidents", "no"),
        answer("company-uses-tax-reliefs", "uses_tax_reliefs", "no"),
    )
    return CompanyTaxProfile(
        company_external_id="company-1",
        profile_version=profile_version,
        valid_from=date(2026, 7, 25),
        questionnaire_version=1,
        answers=answers,
        created_at=NOW,
    )


def test_questionnaire_is_versioned_fixed_and_checksum_protected() -> None:
    catalog = TaxQuestionnaireRepository().load_georgia()

    assert catalog.version == 1
    assert catalog.jurisdiction == "GE"
    assert len(catalog.questions) == 24
    assert catalog.question("vat-registration").fact_id == (
        "vat_registration_status"
    )
    assert {item.value for item in catalog.question("company-legal-form").options} >= {
        "individual_entrepreneur",
        "limited_liability_company",
        "joint_stock_company",
        "cooperative",
        "unknown",
    }


def test_questionnaire_checksum_rejects_generated_or_modified_question(
    tmp_path: Path,
) -> None:
    raw = json.loads(QUESTIONNAIRE_PATH.read_text(encoding="utf-8"))
    raw["payload"]["questions"][0]["text_ru"] = "Сгенерированный вопрос"
    target = tmp_path / QUESTIONNAIRE_PATH.name
    target.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(TaxQuestionnaireError, match="integrity"):
        TaxQuestionnaireRepository(tmp_path).load_georgia()


def test_branching_asks_individual_regime_only_for_individual_entrepreneur() -> None:
    catalog = TaxQuestionnaireRepository().load_georgia()
    individual = CompanyTaxProfile(
        company_external_id="individual-1",
        profile_version=1,
        valid_from=date(2026, 7, 25),
        questionnaire_version=1,
        answers=(
            answer(
                "company-legal-form",
                "legal_form",
                "individual_entrepreneur",
            ),
        ),
        created_at=NOW,
    )

    assessment = assess_tax_profile(
        individual,
        catalog,
        on_date=date(2026, 7, 25),
    )
    visible_ids = {item.question_id for item in assessment.visible_questions}

    assert "individual-special-regime" in visible_ids
    assert "company-special-statuses" not in visible_ids
    assert assessment.readiness is TaxProfileReadiness.INCOMPLETE


def test_complete_company_profile_has_no_unanswered_required_questions() -> None:
    assessment = assess_tax_profile(
        complete_company_profile(),
        TaxQuestionnaireRepository().load_georgia(),
        on_date=date(2026, 7, 25),
    )

    assert assessment.readiness is TaxProfileReadiness.COMPLETE
    assert assessment.unanswered_required_questions == ()
    assert assessment.findings == ()


def test_incompatible_international_and_free_zone_statuses_are_blocked() -> None:
    assessment = assess_tax_profile(
        complete_company_profile(
            special_statuses=(
                "international_company",
                "free_industrial_zone_enterprise",
            )
        ),
        TaxQuestionnaireRepository().load_georgia(),
        on_date=date(2026, 7, 25),
    )

    assert assessment.readiness is TaxProfileReadiness.CONFLICT
    assert any(
        item.code == "international_fiz_status_conflict"
        and item.severity is ProfileFindingSeverity.ERROR
        for item in assessment.findings
    )


def test_micro_business_with_employees_is_a_profile_conflict() -> None:
    profile = CompanyTaxProfile(
        company_external_id="individual-1",
        profile_version=1,
        valid_from=date(2026, 7, 25),
        questionnaire_version=1,
        answers=(
            answer(
                "company-legal-form",
                "legal_form",
                "individual_entrepreneur",
            ),
            answer(
                "individual-special-regime",
                "individual_special_regime",
                "micro_business",
                source_reference="certificate:micro",
            ),
            answer("company-has-employees", "has_employees", "yes"),
        ),
        created_at=NOW,
    )

    assessment = assess_tax_profile(
        profile,
        TaxQuestionnaireRepository().load_georgia(),
        on_date=date(2026, 7, 25),
    )

    assert assessment.readiness is TaxProfileReadiness.CONFLICT
    assert "micro_business_employee_conflict" in {
        item.code for item in assessment.findings
    }


def test_import_detail_question_appears_only_after_confirmed_import_activity() -> None:
    catalog = TaxQuestionnaireRepository().load_georgia()
    no_import = complete_company_profile()
    with_import = CompanyTaxProfile(
        company_external_id=no_import.company_external_id,
        profile_version=no_import.profile_version,
        valid_from=no_import.valid_from,
        questionnaire_version=no_import.questionnaire_version,
        answers=tuple(
            item
            if item.fact_id != "has_import_activity"
            else answer("company-imports-goods", "has_import_activity", "yes")
            for item in no_import.answers
        ),
        created_at=no_import.created_at,
    )

    no_import_visible = {
        item.question_id
        for item in assess_tax_profile(
            no_import,
            catalog,
            on_date=date(2026, 7, 25),
        ).visible_questions
    }
    import_assessment = assess_tax_profile(
        with_import,
        catalog,
        on_date=date(2026, 7, 25),
    )

    assert "import-codes-available" not in no_import_visible
    assert "import-codes-available" in {
        item.question_id for item in import_assessment.visible_questions
    }
    assert "import-codes-available" in {
        item.question_id
        for item in import_assessment.unanswered_required_questions
    }


def test_missing_status_document_is_reported_without_ai_guessing() -> None:
    profile = complete_company_profile(
        special_statuses=("international_company",)
    )
    status_answer = profile.answer_by_fact("company_special_statuses")
    assert status_answer is not None
    profile = CompanyTaxProfile(
        company_external_id=profile.company_external_id,
        profile_version=profile.profile_version,
        valid_from=profile.valid_from,
        questionnaire_version=profile.questionnaire_version,
        answers=tuple(
            item
            if item.fact_id != "company_special_statuses"
            else TaxProfileAnswer(
                question_id=item.question_id,
                fact_id=item.fact_id,
                values=item.values,
                effective_from=item.effective_from,
                effective_through=item.effective_through,
                source=item.source,
                verification_status=VerificationStatus.UNVERIFIED,
                answered_at=item.answered_at,
                source_reference="",
            )
            for item in profile.answers
        ),
        created_at=profile.created_at,
    )

    assessment = assess_tax_profile(
        profile,
        TaxQuestionnaireRepository().load_georgia(),
        on_date=date(2026, 7, 25),
    )

    assert assessment.readiness is TaxProfileReadiness.COMPLETE
    assert "tax_profile_evidence_missing" in {
        item.code for item in assessment.findings
    }


def test_profile_facts_join_with_transaction_facts_for_rate_readiness() -> None:
    profile = complete_company_profile()
    profit_rule = TaxRateCatalogRepository().load_georgia().rule(
        "ge-profit-rates"
    )

    readiness = assess_tax_rule_facts(
        profit_rule,
        profile,
        on_date=date(2026, 7, 25),
        transaction_fact_ids=frozenset(
            {
                "taxable_operation_type",
                "distributed_and_deemed_distribution_amounts",
                "legacy_oil_gas_contract_status",
                "gambling_activity_and_participant_status",
            }
        ),
    )

    assert readiness.ready is True
    assert "entity_tax_status" in readiness.available_fact_ids
    assert "applicable_reliefs" in readiness.available_fact_ids
    assert readiness.missing_facts == ()


def test_tax_profile_versions_are_recorded_and_loaded_locally(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'history.db'}")
    migrate_database(engine)
    repository = SqlAlchemyTaxProfileRepository(
        sessionmaker(bind=engine, expire_on_commit=False)
    )
    profile = complete_company_profile()

    repository.record(profile)
    loaded = repository.load_latest("company-1", on_date=date(2026, 7, 25))

    assert loaded is not None
    assert loaded.company_external_id == profile.company_external_id
    assert loaded.profile_version == profile.profile_version
    assert loaded.fact_values(on_date=date(2026, 7, 25)) == profile.fact_values(
        on_date=date(2026, 7, 25)
    )
    with pytest.raises(TaxProfileRepositoryError, match="already exists"):
        repository.record(profile)
    with pytest.raises(Exception, match="immutable"):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE tax_profile_versions "
                    "SET profile_version = 2 WHERE company_external_id = 'company-1'"
                )
            )


def test_tax_profile_hash_detects_database_tampering(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'tampered.db'}")
    Base.metadata.create_all(engine)
    repository = SqlAlchemyTaxProfileRepository(
        sessionmaker(bind=engine, expire_on_commit=False)
    )
    repository.record(complete_company_profile())
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE tax_profile_versions "
                "SET content_json = replace(content_json, 'retail_trade', 'other')"
            )
        )

    with pytest.raises(TaxProfileRepositoryError, match="integrity"):
        repository.load_latest("company-1")
