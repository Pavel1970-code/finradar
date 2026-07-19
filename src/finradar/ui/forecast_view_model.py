from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from finradar.application.fiscal_comparison import FiscalComparisonStatus
from finradar.application.synchronization_service import SynchronizationOutcome
from finradar.domain.data_readiness import IssueSeverity
from finradar.domain.fiscal_consequences import ConsequenceStatus


@dataclass(frozen=True, slots=True)
class DataGapView:
    blocking: bool
    message: str
    impact: str


@dataclass(frozen=True, slots=True)
class FiscalObligationView:
    title: str
    rate: Decimal
    amount: Decimal
    outstanding_amount: Decimal
    currency: str
    due_date: date


@dataclass(frozen=True, slots=True)
class FiscalConsequenceView:
    title: str
    status_text: str
    amount: Decimal | None
    currency: str
    assessment_date: date
    warning: bool


@dataclass(frozen=True, slots=True)
class FiscalComparisonView:
    resolved: bool
    baseline_rate: Decimal | None = None
    current_rate: Decimal | None = None
    baseline_obligation: Decimal | None = None
    current_obligation: Decimal | None = None
    baseline_funding: Decimal | None = None
    current_funding: Decimal | None = None
    obligation_delta: Decimal | None = None
    funding_delta: Decimal | None = None


@dataclass(frozen=True, slots=True)
class ForecastViewModel:
    currency: str
    data_gaps: tuple[DataGapView, ...]
    obligations: tuple[FiscalObligationView, ...]
    consequences: tuple[FiscalConsequenceView, ...]
    comparison: FiscalComparisonView | None


def build_forecast_view_model(outcome: SynchronizationOutcome) -> ForecastViewModel:
    currency = outcome.snapshot.company.base_currency if outcome.snapshot.company else ""
    gaps = tuple(
        DataGapView(
            blocking=item.severity is IssueSeverity.ERROR,
            message=_issue_text(item.code, item.message, item.impact)[0],
            impact=_issue_text(item.code, item.message, item.impact)[1],
        )
        for item in outcome.readiness.issues
    )
    obligations = tuple(
        FiscalObligationView(
            title=obligation.title,
            rate=obligation.rate,
            amount=obligation.amount,
            outstanding_amount=(
                analysis.reconciliation.outstanding_amount
                if analysis.reconciliation is not None
                else obligation.amount
            ),
            currency=obligation.currency,
            due_date=obligation.due_date,
        )
        for analysis in outcome.rule_analyses
        if (obligation := analysis.calculation.obligation) is not None
    )
    consequences = tuple(
        FiscalConsequenceView(
            title={
                "late_payment_penalty": "Пеня",
                "fine": "Штраф",
            }.get(item.consequence_type, "Фискальное последствие"),
            status_text={
                ConsequenceStatus.ACCRUED: "Учтено в бухгалтерских данных",
                ConsequenceStatus.CALCULATED: "Расчётное последствие",
                ConsequenceStatus.CONTINGENT: (
                    "Возможное последствие в стресс-сценарии"
                ),
                ConsequenceStatus.UNRESOLVED: "Недостаточно данных для расчёта",
            }[item.status],
            amount=item.amount,
            currency=item.currency,
            assessment_date=item.assessment_date,
            warning=item.status
            in {ConsequenceStatus.CONTINGENT, ConsequenceStatus.UNRESOLVED},
        )
        for item in outcome.consequences
    )
    comparison = _comparison_view(outcome)
    return ForecastViewModel(
        currency=currency,
        data_gaps=gaps,
        obligations=obligations,
        consequences=consequences,
        comparison=comparison,
    )


def _comparison_view(outcome: SynchronizationOutcome) -> FiscalComparisonView | None:
    comparison = outcome.fiscal_comparison
    if comparison is None:
        return None
    if comparison.status is FiscalComparisonStatus.UNRESOLVED:
        return FiscalComparisonView(resolved=False)
    baseline = comparison.baseline
    current = comparison.current
    assert baseline is not None and current is not None
    return FiscalComparisonView(
        resolved=True,
        baseline_rate=baseline.rate,
        current_rate=current.rate,
        baseline_obligation=baseline.obligation_amount,
        current_obligation=current.obligation_amount,
        baseline_funding=baseline.forecast.required_funding,
        current_funding=current.forecast.required_funding,
        obligation_delta=comparison.obligation_delta,
        funding_delta=comparison.required_funding_delta,
    )


def _issue_text(code: str, message: str, impact: str) -> tuple[str, str]:
    translations = {
        "company_profile_missing": (
            "Источник не передал профиль компании.",
            "Нельзя определить применимость фискальных правил и построить прогноз.",
        ),
        "account_balances_unavailable": (
            "Остатки по счетам недоступны.",
            "Невозможно определить начальную денежную позицию.",
        ),
        "account_balances_empty": (
            "Источник не вернул активных денежных счетов.",
            "Невозможно определить начальную денежную позицию.",
        ),
        "account_balance_stale": (
            "Остаток хотя бы одного счёта устарел.",
            "Прогноз начинается с потенциально неактуального остатка.",
        ),
        "account_currency_incompatible": (
            "Валюта хотя бы одного счёта отличается от валюты компании.",
            "Для общего прогноза нужна явно заданная политика конвертации.",
        ),
        "payment_calendar_unavailable": (
            "Источник не передал платёжный календарь.",
            "В прогнозе могут отсутствовать будущие поступления и платежи.",
        ),
        "accounting_facts_unavailable": (
            "Источник не передал показатели для налогового анализа.",
            "Часть обязательств может остаться нерассчитанной.",
        ),
        "event_currency_incompatible": (
            "Валюта хотя бы одного события отличается от валюты компании.",
            "Событие нельзя учитывать без политики конвертации.",
        ),
        "jurisdiction_missing": (
            "Не указана юрисдикция компании.",
            "Нельзя выбрать применимые фискальные правила.",
        ),
        "tax_regime_missing": (
            "Не указан налоговый режим компании.",
            "Нельзя надёжно рассчитать обязательства и льготы.",
        ),
        "one_c_company_mapping_failed": (
            "Карточка компании из 1С заполнена или сопоставлена не полностью.",
            "Нельзя надёжно определить компанию и применимые правила.",
        ),
        "one_c_balance_mapping_failed": (
            "Одна из записей об остатках из 1С не прошла проверку.",
            "Запись исключена; начальный остаток может быть неполным.",
        ),
        "one_c_metric_mapping_failed": (
            "Один из бухгалтерских показателей из 1С не прошёл проверку.",
            "Некоторые обязательства могут остаться нерассчитанными.",
        ),
        "one_c_accounting_event_mapping_failed": (
            "Одна из фактических операций 1С не прошла проверку.",
            "Фактические поступления или расходы могут быть отражены не полностью.",
        ),
        "one_c_payment_event_mapping_failed": (
            "Одна из записей платёжного календаря 1С не прошла проверку.",
            "Прогноз будущих поступлений и расходов может быть неполным.",
        ),
        "bank_transactions_unavailable": (
            "Банковские операции недоступны.",
            "Нельзя сверить последние поступления и расходы с бухгалтерией.",
        ),
        "bank_statements_empty": (
            "Банк не передал ни одной выписки.",
            "Нельзя подтвердить последние движения денежных средств.",
        ),
        "bank_coverage_stale": (message, impact),
        "bank_transactions_missing_in_accounting": (message, impact),
        "bank_reconciliation_ambiguous": (message, impact),
        "bank_reconciliation_conflict": (message, impact),
        "bank_statement_balance_mismatch": (
            "Операции выписки не сходятся с её конечным остатком.",
            "Выписка может быть неполной или содержать неподдерживаемую операцию.",
        ),
        "bank_accounting_balance_mismatch": (
            "Остаток банка отличается от остатка бухгалтерии на ту же дату.",
            "Начальная денежная позиция требует сверки.",
        ),
        "bank_duplicate_transaction": (
            "В банковской выписке обнаружена повторная операция.",
            "Повтор исключён из сверки.",
        ),
        "bank_transaction_id_derived": (
            "У банковской операции отсутствует стабильный идентификатор.",
            "Соответствие такой операции менее надёжно.",
        ),
        "bank_row_mapping_failed": (
            "Одна из строк банковской выписки не прошла проверку.",
            "Строка исключена; сверка может быть неполной.",
        ),
    }
    return translations.get(code, (message, impact))
