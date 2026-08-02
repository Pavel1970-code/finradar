import os
from datetime import date
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QComboBox, QFrame, QLabel, QPushButton
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from finradar.application.synchronization_service import synchronize_and_forecast
from finradar.application.tax_profile_readiness import include_tax_profile_readiness
from finradar.application.tax_profile_setup import (
    TaxProfileDraftAnswer,
    TaxProfileSetupContext,
    TaxProfileSetupService,
    tax_profile_context_from_snapshot,
)
from finradar.demo.scenario import DemoScenarioRepository
from finradar.domain.data_readiness import ReadinessReport, ReadinessStatus
from finradar.domain.tax_profile import (
    FactSource,
    TaxProfileReadiness,
    VerificationStatus,
)
from finradar.infrastructure.connectors.demo import DemoAccountingConnector
from finradar.infrastructure.database import migrate_database
from finradar.infrastructure.tax_profile_repository import (
    SqlAlchemyTaxProfileRepository,
)
from finradar.ui.main_window import ForecastUiState, MainWindow
from finradar.ui.tax_profile_wizard import TaxProfileWizard


EFFECTIVE_DATE = date(2026, 7, 18)


def setup_service(tmp_path: Path) -> TaxProfileSetupService:
    engine = create_engine(f"sqlite:///{tmp_path / 'tax-settings.db'}")
    migrate_database(engine)
    return TaxProfileSetupService(
        SqlAlchemyTaxProfileRepository(
            sessionmaker(bind=engine, expire_on_commit=False)
        )
    )


def context() -> TaxProfileSetupContext:
    return TaxProfileSetupContext(
        company_external_id="fictional-company",
        company_name="ООО «Тест»",
        effective_date=EFFECTIVE_DATE,
    )


def draft(question_id: str, *values: str) -> TaxProfileDraftAnswer:
    return TaxProfileDraftAnswer(question_id=question_id, values=values)


def test_snapshot_prefill_uses_only_explicit_accounting_facts() -> None:
    scenario = DemoScenarioRepository().load("georgia_vat_pilot")

    result = tax_profile_context_from_snapshot(
        scenario.accounting_snapshot,
        effective_date=scenario.as_of,
    )
    suggestions = {item.question_id: item.values for item in result.suggestions}

    assert suggestions == {
        "company-tax-residency": ("georgian_enterprise",),
        "vat-registration": ("yes",),
        "company-has-employees": ("yes",),
    }
    assert "company-legal-form" not in suggestions


def test_georgian_questionnaire_rejects_a_non_georgian_demo_company() -> None:
    scenario = DemoScenarioRepository().load("base_cash_gap")

    with pytest.raises(ValueError, match="юрисдикцией GE"):
        tax_profile_context_from_snapshot(
            scenario.accounting_snapshot,
            effective_date=scenario.as_of,
        )


def test_service_saves_immutable_versions_and_skips_an_unchanged_save(
    tmp_path: Path,
) -> None:
    service = setup_service(tmp_path)
    answers = (
        draft("company-legal-form", "limited_liability_company"),
        draft("company-tax-residency", "georgian_enterprise"),
    )

    first = service.save(context(), answers)
    unchanged = service.save(context(), answers)
    changed = service.save(
        context(),
        answers + (draft("vat-registration", "no"),),
    )

    assert first.created_new_version
    assert first.profile.profile_version == 1
    assert not unchanged.created_new_version
    assert unchanged.profile.profile_version == 1
    assert changed.created_new_version
    assert changed.profile.profile_version == 2


def test_accounting_suggestion_remains_unverified_until_user_confirms(
    tmp_path: Path,
) -> None:
    service = setup_service(tmp_path)
    scenario = DemoScenarioRepository().load("georgia_vat_pilot")
    setup_context = tax_profile_context_from_snapshot(
        scenario.accounting_snapshot,
        effective_date=scenario.as_of,
    )

    state = service.load(setup_context)
    answers = {item.question_id: item for item in state.answers}

    assert answers["vat-registration"].source is FactSource.ACCOUNTING_CONNECTOR
    assert (
        answers["vat-registration"].verification_status
        is VerificationStatus.UNVERIFIED
    )
    assert "tax_profile_unverified_fact" in {
        item.code for item in state.assessment.findings
    }


def test_hidden_branch_answers_are_not_written_to_the_new_version(
    tmp_path: Path,
) -> None:
    service = setup_service(tmp_path)
    answers = (
        draft("company-legal-form", "limited_liability_company"),
        draft("company-special-statuses", "virtual_zone_person"),
    )
    service.save(context(), answers)

    changed = service.save(
        context(),
        (
            draft("company-legal-form", "individual_entrepreneur"),
            draft("company-special-statuses", "virtual_zone_person"),
        ),
    )

    assert changed.profile.answer_by_question("company-special-statuses") is None
    visible = {
        item.question_id for item in changed.assessment.visible_questions
    }
    assert "individual-special-regime" in visible
    assert "company-special-statuses" not in visible


def test_incomplete_tax_profile_limits_but_does_not_block_cash_forecast(
    tmp_path: Path,
) -> None:
    service = setup_service(tmp_path)
    assessment = service.load(context()).assessment

    report = include_tax_profile_readiness(
        ReadinessReport(status=ReadinessStatus.READY, issues=()),
        assessment,
    )

    assert assessment.readiness is TaxProfileReadiness.INCOMPLETE
    assert report.status is ReadinessStatus.LIMITED
    assert report.issues
    assert all(item.severity.value == "warning" for item in report.issues)
    assert any("юридическая форма" in item.message for item in report.issues)


def test_wizard_shows_one_coded_question_and_can_save_an_incomplete_profile(
    tmp_path: Path,
    qtbot,
) -> None:
    service = setup_service(tmp_path)
    state = service.load(context())
    wizard = TaxProfileWizard(service, state)
    qtbot.addWidget(wizard)
    wizard.show()

    assert wizard.findChild(QLabel, "wizardProgress").text().startswith("Вопрос 1")
    assert "юридическая форма" in wizard.findChild(
        QLabel, "wizardQuestion"
    ).text()
    selector = wizard.findChild(QComboBox, "taxAnswerSelector")
    assert selector.view().objectName() == "taxAnswerMenu"
    selector.showPopup()
    qtbot.wait(20)
    assert selector.view().palette().color(QPalette.ColorRole.Base).name() == "#151c2f"
    assert selector.view().palette().color(QPalette.ColorRole.Text).name() == "#f8fafc"
    selector.hidePopup()
    selector.setCurrentIndex(selector.findData("limited_liability_company"))
    qtbot.mouseClick(
        wizard.findChild(QPushButton, "wizardNextButton"),
        Qt.MouseButton.LeftButton,
    )

    qtbot.waitUntil(
        lambda: "налоговый статус"
        in wizard.findChild(QLabel, "wizardQuestion").text()
    )

    wizard._show_summary()
    assert "Не заполнено обязательных ответов" in wizard.findChild(
        QLabel, "taxProfileSummary"
    ).text()
    qtbot.mouseClick(
        wizard.findChild(QPushButton, "wizardSaveButton"),
        Qt.MouseButton.LeftButton,
    )

    assert wizard.saved_result is not None
    assert wizard.saved_result.profile.profile_version == 1
    assert wizard.saved_result.assessment.readiness is TaxProfileReadiness.INCOMPLETE


def test_desktop_preflight_lists_tax_profile_gaps_without_hiding_forecast(
    tmp_path: Path,
    qtbot,
) -> None:
    service = setup_service(tmp_path)
    outcome = synchronize_and_forecast(
        DemoAccountingConnector(as_of=EFFECTIVE_DATE),
        as_of=EFFECTIVE_DATE,
    )
    window = MainWindow(
        horizon_days=30,
        forecast_runner=lambda: outcome,
        tax_profile_service=service,
        tax_profile_context_provider=lambda scenario_id: context(),
    )
    qtbot.addWidget(window)
    window.show()

    assert window.findChild(QFrame, "companySettingsCard") is not None
    qtbot.mouseClick(
        window.findChild(QPushButton, "forecastButton"),
        Qt.MouseButton.LeftButton,
    )
    qtbot.waitUntil(lambda: window.state is ForecastUiState.RESULT)
    qtbot.waitUntil(lambda: window._worker is None)
    texts = "\n".join(label.text() for label in window.findChildren(QLabel))

    assert "Анализ возможен с ограничениями" in texts
    assert "Не указан налоговый параметр" in texts
    assert window.findChildren(QLabel, "metricCaption")
