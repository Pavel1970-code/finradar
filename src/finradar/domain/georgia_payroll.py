from __future__ import annotations

from dataclasses import dataclass
from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum

from finradar.domain.payroll import (
    PayrollRecord,
    PayrollRecordStatus,
    PayrollPaymentForm,
    PayrollTaxTreatment,
    PensionParticipationStatus,
)


MONEY_QUANTUM = Decimal("0.01")


class PayrollCheckSeverity(str, Enum):
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class PayrollLegalSource:
    source_id: str
    title: str
    url: str
    provisions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StateCofinancingTier:
    lower_bound: Decimal
    upper_bound: Decimal | None
    rate: Decimal


@dataclass(frozen=True, slots=True)
class GeorgiaPayrollRules:
    version: int
    verified_on: date
    standard_income_tax_rate: Decimal
    employee_pension_rate: Decimal
    employer_pension_rate: Decimal
    state_cofinancing_tiers: tuple[StateCofinancingTier, ...]
    payroll_declaration_day: int
    sources: tuple[PayrollLegalSource, ...]


@dataclass(frozen=True, slots=True)
class PayrollCheck:
    code: str
    severity: PayrollCheckSeverity
    message: str
    impact: str
    source_reference: str


CURRENT_GEORGIA_PAYROLL_RULES = GeorgiaPayrollRules(
    version=1,
    verified_on=date(2026, 7, 25),
    standard_income_tax_rate=Decimal("0.20"),
    employee_pension_rate=Decimal("0.02"),
    employer_pension_rate=Decimal("0.02"),
    state_cofinancing_tiers=(
        StateCofinancingTier(
            lower_bound=Decimal("0"),
            upper_bound=Decimal("24000"),
            rate=Decimal("0.02"),
        ),
        StateCofinancingTier(
            lower_bound=Decimal("24000"),
            upper_bound=Decimal("60000"),
            rate=Decimal("0.01"),
        ),
        StateCofinancingTier(
            lower_bound=Decimal("60000"),
            upper_bound=None,
            rate=Decimal("0"),
        ),
    ),
    payroll_declaration_day=15,
    sources=(
        PayrollLegalSource(
            source_id="ge-tax-code-245",
            title="Налоговый кодекс Грузии, публикация 245",
            url="https://matsne.gov.ge/ka/document/download/1043717/245/ge/pdf",
            provisions=("статьи 4(6), 81(1), 101, 153(5), 154"),
        ),
        PayrollLegalSource(
            source_id="ge-funded-pension-law-12",
            title="Закон Грузии «О накопительной пенсии», публикация 12",
            url="https://www.matsne.gov.ge/ka/document/download/4280127/12/ge/pdf",
            provisions=("статьи 1(4), 3(2)–(6)"),
        ),
        PayrollLegalSource(
            source_id="ge-pension-procedure-2025",
            title="Инструкция Пенсионного фонда о пенсионных взносах",
            url="https://matsne.gov.ge/ka/document/view/6493226",
            provisions=("порядок после 1 мая 2025 года",),
        ),
    ),
)


def validate_georgian_payroll_record(
    record: PayrollRecord,
    rules: GeorgiaPayrollRules,
    *,
    non_business_dates: frozenset[date] = frozenset(),
) -> tuple[PayrollCheck, ...]:
    if record.status is PayrollRecordStatus.CANCELLED:
        return ()

    checks: list[PayrollCheck] = []
    reference = record.source_reference or record.external_id
    expected_net = money(
        record.gross_cash_compensation - record.employee_deductions
    )
    if record.net_salary_payable != expected_net:
        checks.append(
            PayrollCheck(
                code="payroll_net_arithmetic_mismatch",
                severity=PayrollCheckSeverity.ERROR,
                message="Чистая зарплата не совпадает с валовой денежной выплатой минус удержания.",
                impact="Разложение зарплаты неоднозначно и не может безопасно использоваться в прогнозе.",
                source_reference=reference,
            )
        )

    if record.tax_treatment is PayrollTaxTreatment.STANDARD:
        expected_tax = money(
            record.income_tax_base * rules.standard_income_tax_rate
        )
        if record.income_tax_withheld != expected_tax:
            checks.append(
                PayrollCheck(
                    code="payroll_income_tax_mismatch",
                    severity=PayrollCheckSeverity.ERROR,
                    message=(
                        "Удержанный подоходный налог не соответствует переданной "
                        "налоговой базе и стандартной ставке."
                    ),
                    impact="Налоговый платёж нельзя считать проверенным.",
                    source_reference=reference,
                )
            )
    elif record.tax_treatment is PayrollTaxTreatment.SOURCE_REPORTED_EXCEPTION:
        if not record.tax_treatment_reference.strip():
            checks.append(
                PayrollCheck(
                    code="payroll_tax_exception_reference_missing",
                    severity=PayrollCheckSeverity.WARNING,
                    message="Для нестандартного налогообложения зарплаты не указано основание.",
                    impact="Льготу или исключение нельзя проверить по нормативному правилу.",
                    source_reference=reference,
                )
            )
    else:
        checks.append(
            PayrollCheck(
                code="payroll_tax_treatment_unknown",
                severity=PayrollCheckSeverity.WARNING,
                message="Не определён режим подоходного налога для зарплатной строки.",
                impact="Система не может проверить удержанный налог.",
                source_reference=reference,
            )
        )

    if record.pension_participation is PensionParticipationStatus.PARTICIPANT:
        expected_employee = money(
            record.pension_contribution_base * rules.employee_pension_rate
        )
        expected_employer = money(
            record.pension_contribution_base * rules.employer_pension_rate
        )
        if record.employee_pension_contribution != expected_employee:
            checks.append(
                PayrollCheck(
                    code="payroll_employee_pension_mismatch",
                    severity=PayrollCheckSeverity.ERROR,
                    message="Пенсионный взнос работника не соответствует пенсионной базе.",
                    impact="Удержание работника нельзя считать проверенным.",
                    source_reference=reference,
                )
            )
        if record.employer_pension_contribution != expected_employer:
            checks.append(
                PayrollCheck(
                    code="payroll_employer_pension_mismatch",
                    severity=PayrollCheckSeverity.ERROR,
                    message="Пенсионный взнос работодателя не соответствует пенсионной базе.",
                    impact="Дополнительный расход работодателя рассчитан неверно.",
                    source_reference=reference,
                )
            )
        if (
            record.state_pension_cofinancing is not None
            and record.annual_pension_base_before is not None
        ):
            expected_state = calculate_state_cofinancing(
                record.pension_contribution_base,
                annual_base_before=record.annual_pension_base_before,
                tiers=rules.state_cofinancing_tiers,
            )
            if record.state_pension_cofinancing != expected_state:
                checks.append(
                    PayrollCheck(
                        code="payroll_state_pension_mismatch",
                        severity=PayrollCheckSeverity.WARNING,
                        message="Государственное пенсионное софинансирование не совпадает с годовыми порогами.",
                        impact="Это не меняет денежный поток компании, но указывает на несогласованность данных.",
                        source_reference=reference,
                    )
                )
    elif record.pension_participation is PensionParticipationStatus.NOT_PARTICIPANT:
        if any(
            amount != Decimal("0")
            for amount in (
                record.pension_contribution_base,
                record.employee_pension_contribution,
                record.employer_pension_contribution,
                record.state_pension_cofinancing or Decimal("0"),
            )
        ):
            checks.append(
                PayrollCheck(
                    code="payroll_pension_for_non_participant",
                    severity=PayrollCheckSeverity.ERROR,
                    message="Для работника вне пенсионной схемы переданы пенсионные суммы.",
                    impact="Статус участия или суммы должны быть исправлены.",
                    source_reference=reference,
                )
            )
    else:
        checks.append(
            PayrollCheck(
                code="payroll_pension_status_unknown",
                severity=PayrollCheckSeverity.WARNING,
                message="Не определён статус участия работника в накопительной пенсионной схеме.",
                impact="Нельзя подтвердить пенсионные удержания и расход работодателя.",
                source_reference=reference,
            )
        )

    expected_declaration_date = next_working_day(
        date(
            record.payment_date.year + (record.payment_date.month == 12),
            1 if record.payment_date.month == 12 else record.payment_date.month + 1,
            rules.payroll_declaration_day,
        ),
        non_business_dates=non_business_dates,
    )
    if record.payment_form is PayrollPaymentForm.CASH:
        expected_tax_due_date = record.payment_date
    elif record.payment_form is PayrollPaymentForm.NON_CASH:
        expected_tax_due_date = next_working_day(
            date(
                record.payment_date.year,
                record.payment_date.month,
                monthrange(
                    record.payment_date.year,
                    record.payment_date.month,
                )[1],
            ),
            non_business_dates=non_business_dates,
        )
    else:
        expected_tax_due_date = None
        checks.append(
            PayrollCheck(
                code="payroll_mixed_payment_requires_split",
                severity=PayrollCheckSeverity.ERROR,
                message="Смешанная денежная и неденежная зарплата должна быть разделена по срокам налога.",
                impact="Для денежной и неденежной частей закон устанавливает разные моменты перечисления.",
                source_reference=reference,
            )
        )
    if (
        expected_tax_due_date is not None
        and record.income_tax_remittance_due_date != expected_tax_due_date
    ):
        checks.append(
            PayrollCheck(
                code="payroll_income_tax_due_date_mismatch",
                severity=PayrollCheckSeverity.WARNING,
                message="Срок перечисления удержанного налога не соответствует форме выплаты.",
                impact="Прогноз может показать налог позже установленного срока.",
                source_reference=reference,
            )
        )
    if record.payroll_declaration_due_date != expected_declaration_date:
        checks.append(
            PayrollCheck(
                code="payroll_declaration_due_date_mismatch",
                severity=PayrollCheckSeverity.WARNING,
                message="Срок зарплатной декларации не совпадает с установленным сроком.",
                impact="Календарь отчётности требует проверки.",
                source_reference=reference,
            )
        )
    if (
        record.pension_participation is PensionParticipationStatus.PARTICIPANT
        and record.pension_contribution_due_date != expected_declaration_date
    ):
        checks.append(
            PayrollCheck(
                code="payroll_pension_due_date_mismatch",
                severity=PayrollCheckSeverity.WARNING,
                message="Срок пенсионного перечисления не совпадает со сроком зарплатной декларации.",
                impact="Пенсионный платёж может быть запланирован позже допустимого срока.",
                source_reference=reference,
            )
        )
    return tuple(checks)


def calculate_state_cofinancing(
    amount: Decimal,
    *,
    annual_base_before: Decimal,
    tiers: tuple[StateCofinancingTier, ...],
) -> Decimal:
    remaining = amount
    cursor = annual_base_before
    result = Decimal("0")
    for tier in tiers:
        if remaining <= 0:
            break
        if cursor < tier.lower_bound:
            skipped = min(remaining, tier.lower_bound - cursor)
            remaining -= skipped
            cursor += skipped
        if remaining <= 0:
            break
        if tier.upper_bound is None:
            eligible = remaining
        else:
            if cursor >= tier.upper_bound:
                continue
            eligible = min(remaining, tier.upper_bound - cursor)
        result += eligible * tier.rate
        remaining -= eligible
        cursor += eligible
    return money(result)


def next_working_day(
    value: date,
    *,
    non_business_dates: frozenset[date] = frozenset(),
) -> date:
    current = value
    while current.weekday() >= 5 or current in non_business_dates:
        current += timedelta(days=1)
    return current


def money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
