from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from finradar.application.tax_profile_setup import (
    SavedTaxProfile,
    TaxProfileDraftAnswer,
    TaxProfileSetupService,
    TaxProfileSetupState,
)
from finradar.domain.tax_profile import (
    AnswerKind,
    FactSource,
    TaxProfileQuestion,
    TaxProfileReadiness,
    VerificationStatus,
)


class TaxProfileWizard(QDialog):
    profile_saved = Signal(object)

    def __init__(
        self,
        service: TaxProfileSetupService,
        state: TaxProfileSetupState,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._state = state
        self._answers = {item.question_id: item for item in state.answers}
        self._current_question_id: str | None = None
        self._answer_widget: QWidget | None = None
        self._evidence_input: QLineEdit | None = None
        self._multiple_inputs: dict[str, QCheckBox] = {}
        self.saved_result: SavedTaxProfile | None = None

        self.setObjectName("taxProfileWizard")
        self.setWindowTitle("Настройки компании — FinRadar")
        self.resize(760, 620)
        self.setMinimumSize(640, 520)

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(18)

        title = QLabel("Настройки компании")
        title.setObjectName("wizardTitle")
        company = QLabel(
            f"{state.context.company_name}\n"
            f"Параметры действуют с "
            f"{state.context.effective_date.strftime('%d.%m.%Y')}"
        )
        company.setObjectName("wizardCompany")
        company.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(company)

        self._body = QWidget()
        self._body.setObjectName("wizardBody")
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(0, 0, 0, 0)
        self._page = QWidget(self._body)
        self._page_layout = QVBoxLayout(self._page)
        self._page_layout.setContentsMargins(0, 0, 0, 0)
        self._body_layout.addWidget(self._page)
        root.addWidget(self._body, 1)

        self._apply_styles()
        visible = self._visible_questions()
        if visible:
            self._show_question(visible[0].question_id)
        else:
            self._show_summary()

    def _visible_questions(self) -> tuple[TaxProfileQuestion, ...]:
        assessment = self._service.assess(
            self._state.context,
            tuple(self._answers.values()),
            profile_version=(
                self._state.latest_profile.profile_version
                if self._state.latest_profile is not None
                else 1
            ),
        )
        return assessment.visible_questions

    def _clear_body(self) -> None:
        previous = self._page
        self._body_layout.removeWidget(previous)
        for widget in previous.findChildren(QWidget):
            widget.setObjectName("")
        previous.hide()
        previous.deleteLater()
        self._page = QWidget(self._body)
        self._page_layout = QVBoxLayout(self._page)
        self._page_layout.setContentsMargins(0, 0, 0, 0)
        self._body_layout.addWidget(self._page)
        self._answer_widget = None
        self._evidence_input = None
        self._multiple_inputs = {}

    def _show_question(self, question_id: str) -> None:
        self._clear_body()
        visible = self._visible_questions()
        question_ids = [item.question_id for item in visible]
        if question_id not in question_ids:
            self._show_summary()
            return
        self._current_question_id = question_id
        question = self._state.catalog.question(question_id)
        position = question_ids.index(question_id)

        progress = QLabel(f"Вопрос {position + 1} из {len(visible)}")
        progress.setObjectName("wizardProgress")
        prompt = QLabel(question.text_ru)
        prompt.setObjectName("wizardQuestion")
        prompt.setWordWrap(True)
        help_text = QLabel(question.help_ru)
        help_text.setObjectName("wizardHelp")
        help_text.setWordWrap(True)
        self._page_layout.addWidget(progress)
        self._page_layout.addWidget(prompt)
        self._page_layout.addWidget(help_text)

        if question_id in self._state.suggested_question_ids:
            suggestion = QLabel(
                "Ответ получен из учётных данных. Проверьте его перед продолжением."
            )
            suggestion.setObjectName("wizardSuggestion")
            suggestion.setWordWrap(True)
            self._page_layout.addWidget(suggestion)

        current = self._answers.get(question_id)
        self._answer_widget = self._create_answer_widget(question, current)
        self._page_layout.addWidget(self._answer_widget)

        if question.source_reference_required_for:
            evidence_label = QLabel("Подтверждающий документ или источник")
            evidence_label.setObjectName("wizardFieldLabel")
            evidence = QLineEdit()
            evidence.setObjectName("taxEvidenceInput")
            evidence.setPlaceholderText("Например: номер решения или регистрационной записи")
            if current is not None:
                evidence.setText(current.source_reference)
            self._evidence_input = evidence
            self._page_layout.addWidget(evidence_label)
            self._page_layout.addWidget(evidence)

        self._page_layout.addStretch()
        navigation = QHBoxLayout()
        back = QPushButton("Назад")
        back.setObjectName("wizardBackButton")
        back.setEnabled(position > 0)
        back.clicked.connect(self._go_back)
        skip = QPushButton("Пока пропустить")
        skip.setObjectName("wizardSkipButton")
        skip.clicked.connect(self._skip)
        next_button = QPushButton("Продолжить")
        next_button.setObjectName("wizardNextButton")
        next_button.clicked.connect(self._advance)
        navigation.addWidget(back)
        navigation.addStretch()
        navigation.addWidget(skip)
        navigation.addWidget(next_button)
        self._page_layout.addLayout(navigation)

    def _create_answer_widget(
        self,
        question: TaxProfileQuestion,
        current: TaxProfileDraftAnswer | None,
    ) -> QWidget:
        if question.answer_kind is AnswerKind.SINGLE_CHOICE:
            selector = QComboBox()
            selector.setObjectName("taxAnswerSelector")
            selector.view().setObjectName("taxAnswerMenu")
            selector.addItem("Выберите вариант", None)
            for option in question.options:
                selector.addItem(option.label_ru, option.value)
            if current is not None:
                index = selector.findData(current.values[0])
                if index >= 0:
                    selector.setCurrentIndex(index)
            return selector

        if question.answer_kind is AnswerKind.MULTIPLE_CHOICE:
            frame = QFrame()
            frame.setObjectName("taxMultipleAnswers")
            layout = QVBoxLayout(frame)
            layout.setContentsMargins(14, 12, 14, 12)
            selected = set(current.values if current is not None else ())
            exclusive_values = {"none", "unknown"}
            for option in question.options:
                checkbox = QCheckBox(option.label_ru)
                checkbox.setObjectName(f"taxOption_{option.value}")
                checkbox.setChecked(option.value in selected)
                checkbox.toggled.connect(
                    lambda checked, value=option.value: self._multiple_toggled(
                        value,
                        checked,
                        exclusive_values,
                    )
                )
                self._multiple_inputs[option.value] = checkbox
                layout.addWidget(checkbox)
            return frame

        editor = QLineEdit()
        editor.setObjectName("taxAnswerInput")
        if question.answer_kind is AnswerKind.DATE:
            editor.setPlaceholderText("ГГГГ-ММ-ДД")
        elif question.answer_kind is AnswerKind.DECIMAL:
            editor.setPlaceholderText("0.00")
        else:
            editor.setPlaceholderText("Введите ответ")
        if current is not None:
            editor.setText(current.values[0])
        return editor

    def _multiple_toggled(
        self,
        value: str,
        checked: bool,
        exclusive_values: set[str],
    ) -> None:
        if not checked:
            return
        if value in exclusive_values:
            targets: Iterable[tuple[str, QCheckBox]] = self._multiple_inputs.items()
            for other_value, checkbox in targets:
                if other_value != value:
                    checkbox.setChecked(False)
        else:
            for exclusive in exclusive_values:
                checkbox = self._multiple_inputs.get(exclusive)
                if checkbox is not None:
                    checkbox.setChecked(False)

    def _read_values(self, question: TaxProfileQuestion) -> tuple[str, ...]:
        if isinstance(self._answer_widget, QComboBox):
            value = self._answer_widget.currentData()
            return (value,) if isinstance(value, str) else ()
        if question.answer_kind is AnswerKind.MULTIPLE_CHOICE:
            return tuple(
                option.value
                for option in question.options
                if self._multiple_inputs[option.value].isChecked()
            )
        if isinstance(self._answer_widget, QLineEdit):
            value = self._answer_widget.text().strip()
            return (value,) if value else ()
        return ()

    def _store_current_answer(self) -> bool:
        if self._current_question_id is None:
            return False
        question = self._state.catalog.question(self._current_question_id)
        values = self._read_values(question)
        if not values:
            QMessageBox.information(
                self,
                "Ответ не выбран",
                "Выберите ответ или нажмите «Пока пропустить».",
            )
            return False
        evidence = self._evidence_input.text() if self._evidence_input is not None else ""
        candidate = TaxProfileDraftAnswer(
            question_id=question.question_id,
            values=values,
            source=FactSource.USER_CONFIRMATION,
            verification_status=(
                VerificationStatus.UNVERIFIED
                if values == ("unknown",)
                else VerificationStatus.USER_CONFIRMED
            ),
            source_reference=evidence.strip(),
        )
        try:
            self._service.assess(self._state.context, (candidate,))
        except ValueError as error:
            QMessageBox.warning(self, "Некорректный ответ", str(error))
            return False
        self._answers[question.question_id] = candidate
        return True

    def _advance(self) -> None:
        if not self._store_current_answer():
            return
        QTimer.singleShot(0, self._move_after_current)

    def _skip(self) -> None:
        if self._current_question_id is not None:
            self._answers.pop(self._current_question_id, None)
        QTimer.singleShot(0, self._move_after_current)

    def _move_after_current(self) -> None:
        current_id = self._current_question_id
        visible = self._visible_questions()
        ids = [item.question_id for item in visible]
        if current_id in ids and ids.index(current_id) + 1 < len(ids):
            self._show_question(ids[ids.index(current_id) + 1])
        else:
            self._show_summary()

    def _go_back(self) -> None:
        if self._current_question_id is None:
            visible = self._visible_questions()
            if visible:
                target = visible[-1].question_id
                QTimer.singleShot(0, lambda: self._show_question(target))
            return
        visible = self._visible_questions()
        ids = [item.question_id for item in visible]
        if self._current_question_id in ids:
            position = ids.index(self._current_question_id)
            if position > 0:
                target = ids[position - 1]
                QTimer.singleShot(0, lambda: self._show_question(target))

    def _show_summary(self) -> None:
        self._clear_body()
        self._current_question_id = None
        assessment = self._service.assess(
            self._state.context,
            tuple(self._answers.values()),
        )
        visible_ids = {item.question_id for item in assessment.visible_questions}
        applicable_answers = tuple(
            item for key, item in self._answers.items() if key in visible_ids
        )
        confirmed = sum(
            item.values != ("unknown",)
            and item.verification_status is not VerificationStatus.UNVERIFIED
            for item in applicable_answers
        )
        unconfirmed = sum(
            item.values != ("unknown",)
            and item.verification_status is VerificationStatus.UNVERIFIED
            for item in applicable_answers
        )
        unknown = sum(item.values == ("unknown",) for item in applicable_answers)

        heading = QLabel("Проверка настроек")
        heading.setObjectName("wizardQuestion")
        summary = QLabel(
            f"Подтверждено ответов: {confirmed}\n"
            f"Получено автоматически, требует подтверждения: {unconfirmed}\n"
            f"Ответов «Не знаю»: {unknown}\n"
            f"Не заполнено обязательных ответов: "
            f"{len(assessment.unanswered_required_questions)}"
        )
        summary.setObjectName("taxProfileSummary")
        summary.setWordWrap(True)
        self._page_layout.addWidget(heading)
        self._page_layout.addWidget(summary)

        if assessment.unanswered_required_questions:
            missing_title = QLabel("Для полного налогового анализа не хватает:")
            missing_title.setObjectName("wizardFieldLabel")
            self._page_layout.addWidget(missing_title)
            scroll = QScrollArea()
            scroll.setObjectName("taxMissingScroll")
            scroll.setWidgetResizable(True)
            missing_widget = QWidget()
            missing_layout = QVBoxLayout(missing_widget)
            for question in assessment.unanswered_required_questions:
                label = QLabel(f"• {question.text_ru}")
                label.setObjectName("taxMissingQuestion")
                label.setWordWrap(True)
                missing_layout.addWidget(label)
            missing_layout.addStretch()
            scroll.setWidget(missing_widget)
            self._page_layout.addWidget(scroll, 1)

        for finding in assessment.findings:
            label = QLabel(finding.message_ru)
            label.setObjectName(
                "taxProfileError"
                if finding.severity.value == "error"
                else "taxProfileWarning"
            )
            label.setWordWrap(True)
            self._page_layout.addWidget(label)

        note = QLabel(
            "Неполный профиль можно сохранить: кассовый прогноз продолжит работать, "
            "но налоговые расчёты будут помечены как ограниченные."
        )
        note.setObjectName("wizardHelp")
        note.setWordWrap(True)
        self._page_layout.addWidget(note)

        navigation = QHBoxLayout()
        back = QPushButton("Вернуться к вопросам")
        back.setObjectName("wizardBackButton")
        back.clicked.connect(self._go_back)
        cancel = QPushButton("Закрыть без сохранения")
        cancel.setObjectName("wizardCancelButton")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Сохранить настройки")
        save.setObjectName("wizardSaveButton")
        save.setEnabled(assessment.readiness is not TaxProfileReadiness.CONFLICT)
        save.clicked.connect(self._save)
        navigation.addWidget(back)
        navigation.addStretch()
        navigation.addWidget(cancel)
        navigation.addWidget(save)
        self._page_layout.addLayout(navigation)

    def _save(self) -> None:
        try:
            result = self._service.save(
                self._state.context,
                tuple(self._answers.values()),
            )
        except ValueError as error:
            QMessageBox.warning(self, "Настройки не сохранены", str(error))
            return
        self.saved_result = result
        self.profile_saved.emit(result)
        self.accept()

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QDialog#taxProfileWizard, QWidget#wizardBody, QScrollArea,
            QScrollArea > QWidget > QWidget {
                background-color: #0b1020;
                color: #f8fafc;
            }
            QLabel#wizardTitle { font-size: 28px; font-weight: 700; color: #f8fafc; }
            QLabel#wizardCompany, QLabel#wizardProgress { color: #94a3b8; font-size: 13px; }
            QLabel#wizardQuestion { color: #f8fafc; font-size: 20px; font-weight: 600; }
            QLabel#wizardHelp { color: #94a3b8; font-size: 14px; }
            QLabel#wizardSuggestion {
                color: #bfdbfe; background-color: #142033; border: 1px solid #2563eb;
                border-radius: 8px; padding: 10px;
            }
            QLabel#wizardFieldLabel { color: #cbd5e1; font-weight: 600; }
            QLabel#taxProfileSummary, QLabel#taxMissingQuestion { color: #e2e8f0; font-size: 14px; }
            QLabel#taxProfileWarning { color: #fde68a; }
            QLabel#taxProfileError { color: #fda4af; }
            QComboBox, QLineEdit {
                color: #f8fafc; background-color: #151c2f; border: 1px solid #334155;
                border-radius: 8px; padding: 10px; min-height: 24px;
            }
            QAbstractItemView#taxAnswerMenu {
                color: #f8fafc;
                background-color: #151c2f;
                border: 1px solid #475569;
                selection-color: #ffffff;
                selection-background-color: #1d4ed8;
                outline: 0;
                padding: 4px;
            }
            QAbstractItemView#taxAnswerMenu::item {
                color: #f8fafc;
                background-color: #151c2f;
                min-height: 34px;
                padding: 5px 9px;
            }
            QAbstractItemView#taxAnswerMenu::item:selected,
            QAbstractItemView#taxAnswerMenu::item:hover {
                color: #ffffff;
                background-color: #1d4ed8;
            }
            QFrame#taxMultipleAnswers {
                background-color: #151c2f; border: 1px solid #334155; border-radius: 8px;
            }
            QCheckBox { color: #e2e8f0; padding: 4px; }
            QPushButton {
                color: #dbeafe; background-color: #142033; border: 1px solid #2563eb;
                border-radius: 8px; padding: 9px 14px;
            }
            QPushButton#wizardNextButton, QPushButton#wizardSaveButton {
                color: #07111f; background-color: #5eead4; border: none; font-weight: 700;
            }
            QPushButton:disabled { color: #64748b; background-color: #26324d; border-color: #334155; }
            """
        )
