import json
from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import TypeAlias

from finradar.domain.fiscal import (
    FiscalRuleStatus,
    GeorgianVatRule,
    PercentageFiscalRule,
)
from finradar.domain.financial_snapshot import (
    CounterpartyKind,
    CounterpartyReference,
)
from finradar.domain.fiscal_consequences import (
    FineRule,
    LatePaymentPenaltyRule,
    PenaltyRatePeriod,
    ViolationType,
)


RuleDefinition: TypeAlias = (
    PercentageFiscalRule | GeorgianVatRule | LatePaymentPenaltyRule | FineRule
)
SCHEMA_VERSION = 3
SUPPORTED_SCHEMA_VERSIONS = {1, 2, 3}


def encode_rule(rule: RuleDefinition) -> tuple[str, str]:
    if isinstance(rule, PercentageFiscalRule):
        rule_type = "percentage_obligation"
        definition = {
            "rule_id": rule.rule_id,
            "version": rule.version,
            "title": rule.title,
            "jurisdiction": rule.jurisdiction,
            "tax_regimes": sorted(rule.tax_regimes),
            "effective_from": rule.effective_from.isoformat(),
            "effective_to": (
                rule.effective_to.isoformat() if rule.effective_to is not None else None
            ),
            "base_metric_code": rule.base_metric_code,
            "rate": str(rule.rate),
            "payment_days_after_period_end": rule.payment_days_after_period_end,
            "obligation_category": rule.obligation_category,
            "source_reference": rule.source_reference,
            "payment_recipient": (
                {
                    "external_id": rule.payment_recipient.external_id,
                    "name": rule.payment_recipient.name,
                    "kind": rule.payment_recipient.kind.value,
                }
                if rule.payment_recipient is not None
                else None
            ),
        }
    elif isinstance(rule, GeorgianVatRule):
        rule_type = "georgian_vat"
        definition = {
            "rule_id": rule.rule_id,
            "version": rule.version,
            "title": rule.title,
            "jurisdiction": rule.jurisdiction,
            "tax_regimes": sorted(rule.tax_regimes),
            "effective_from": rule.effective_from.isoformat(),
            "effective_to": (
                rule.effective_to.isoformat() if rule.effective_to is not None else None
            ),
            "taxable_turnover_metric_code": rule.taxable_turnover_metric_code,
            "deductible_input_vat_metric_code": (
                rule.deductible_input_vat_metric_code
            ),
            "output_adjustment_metric_code": rule.output_adjustment_metric_code,
            "import_vat_metric_code": rule.import_vat_metric_code,
            "reverse_charge_vat_metric_code": rule.reverse_charge_vat_metric_code,
            "excluded_or_mixed_use_metric_code": (
                rule.excluded_or_mixed_use_metric_code
            ),
            "special_transaction_metric_code": rule.special_transaction_metric_code,
            "rate": str(rule.rate),
            "due_day_of_following_month": rule.due_day_of_following_month,
            "obligation_category": rule.obligation_category,
            "source_reference": rule.source_reference,
            "payment_recipient": _counterparty_value(rule.payment_recipient),
            "non_business_dates": sorted(
                item.isoformat() for item in rule.non_business_dates
            ),
        }
    elif isinstance(rule, LatePaymentPenaltyRule):
        rule_type = "late_payment_penalty"
        definition = {
            "rule_id": rule.rule_id,
            "version": rule.version,
            "applies_to_obligation_rule_id": rule.applies_to_obligation_rule_id,
            "grace_days": rule.grace_days,
            "rate_periods": [
                {
                    "effective_from": item.effective_from.isoformat(),
                    "effective_to": (
                        item.effective_to.isoformat()
                        if item.effective_to is not None
                        else None
                    ),
                    "daily_rate": str(item.daily_rate),
                }
                for item in rule.rate_periods
            ],
            "source_reference": rule.source_reference,
        }
    elif isinstance(rule, FineRule):
        rule_type = "fine"
        definition = {
            "rule_id": rule.rule_id,
            "version": rule.version,
            "violation_type": rule.violation_type.value,
            "applies_to_obligation_rule_ids": sorted(
                rule.applies_to_obligation_rule_ids
            ),
            "fixed_amount": _optional_decimal(rule.fixed_amount),
            "percentage_of_outstanding": _optional_decimal(
                rule.percentage_of_outstanding
            ),
            "minimum_amount": _optional_decimal(rule.minimum_amount),
            "maximum_amount": _optional_decimal(rule.maximum_amount),
            "requires_authority_decision": rule.requires_authority_decision,
            "source_reference": rule.source_reference,
        }
    else:
        raise TypeError(f"Unsupported fiscal rule type: {type(rule).__name__}")

    content = {
        "schema_version": SCHEMA_VERSION,
        "rule_type": rule_type,
        "definition": definition,
    }
    return rule_type, json.dumps(
        content,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def decode_rule(content_json: str, *, status: FiscalRuleStatus) -> RuleDefinition:
    payload = json.loads(content_json)
    if payload.get("schema_version") not in SUPPORTED_SCHEMA_VERSIONS:
        raise ValueError("Unsupported fiscal rule schema version.")
    rule_type = payload["rule_type"]
    item = payload["definition"]

    if rule_type == "percentage_obligation":
        return PercentageFiscalRule(
            rule_id=item["rule_id"],
            version=item["version"],
            title=item["title"],
            jurisdiction=item["jurisdiction"],
            tax_regimes=frozenset(item["tax_regimes"]),
            effective_from=date.fromisoformat(item["effective_from"]),
            effective_to=(
                date.fromisoformat(item["effective_to"])
                if item["effective_to"] is not None
                else None
            ),
            base_metric_code=item["base_metric_code"],
            rate=Decimal(item["rate"]),
            payment_days_after_period_end=item["payment_days_after_period_end"],
            obligation_category=item["obligation_category"],
            source_reference=item["source_reference"],
            payment_recipient=(
                CounterpartyReference(
                    external_id=item["payment_recipient"]["external_id"],
                    name=item["payment_recipient"]["name"],
                    kind=CounterpartyKind(item["payment_recipient"]["kind"]),
                )
                if item.get("payment_recipient") is not None
                else None
            ),
            status=status,
        )
    if rule_type == "georgian_vat":
        return GeorgianVatRule(
            rule_id=item["rule_id"],
            version=item["version"],
            title=item["title"],
            jurisdiction=item["jurisdiction"],
            tax_regimes=frozenset(item["tax_regimes"]),
            effective_from=date.fromisoformat(item["effective_from"]),
            effective_to=(
                date.fromisoformat(item["effective_to"])
                if item["effective_to"] is not None
                else None
            ),
            taxable_turnover_metric_code=item["taxable_turnover_metric_code"],
            deductible_input_vat_metric_code=(
                item["deductible_input_vat_metric_code"]
            ),
            output_adjustment_metric_code=item["output_adjustment_metric_code"],
            import_vat_metric_code=item["import_vat_metric_code"],
            reverse_charge_vat_metric_code=item["reverse_charge_vat_metric_code"],
            excluded_or_mixed_use_metric_code=(
                item["excluded_or_mixed_use_metric_code"]
            ),
            special_transaction_metric_code=item["special_transaction_metric_code"],
            rate=Decimal(item["rate"]),
            due_day_of_following_month=item["due_day_of_following_month"],
            obligation_category=item["obligation_category"],
            source_reference=item["source_reference"],
            payment_recipient=_counterparty_from_value(item.get("payment_recipient")),
            non_business_dates=frozenset(
                date.fromisoformat(value)
                for value in item.get("non_business_dates", ())
            ),
            status=status,
        )
    if rule_type == "late_payment_penalty":
        return LatePaymentPenaltyRule(
            rule_id=item["rule_id"],
            version=item["version"],
            applies_to_obligation_rule_id=item["applies_to_obligation_rule_id"],
            grace_days=item["grace_days"],
            rate_periods=tuple(
                PenaltyRatePeriod(
                    effective_from=date.fromisoformat(period["effective_from"]),
                    effective_to=(
                        date.fromisoformat(period["effective_to"])
                        if period["effective_to"] is not None
                        else None
                    ),
                    daily_rate=Decimal(period["daily_rate"]),
                )
                for period in item["rate_periods"]
            ),
            source_reference=item["source_reference"],
            status=status,
        )
    if rule_type == "fine":
        return FineRule(
            rule_id=item["rule_id"],
            version=item["version"],
            violation_type=ViolationType(item["violation_type"]),
            applies_to_obligation_rule_ids=frozenset(
                item["applies_to_obligation_rule_ids"]
            ),
            fixed_amount=_decimal_or_none(item["fixed_amount"]),
            percentage_of_outstanding=_decimal_or_none(
                item["percentage_of_outstanding"]
            ),
            minimum_amount=_decimal_or_none(item["minimum_amount"]),
            maximum_amount=_decimal_or_none(item["maximum_amount"]),
            requires_authority_decision=item["requires_authority_decision"],
            source_reference=item["source_reference"],
            status=status,
        )
    raise ValueError(f"Unsupported fiscal rule type: {rule_type}")


def with_rule_status(
    rule: RuleDefinition,
    status: FiscalRuleStatus,
) -> RuleDefinition:
    return replace(rule, status=status)


def _optional_decimal(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _decimal_or_none(value: str | None) -> Decimal | None:
    return Decimal(value) if value is not None else None


def _counterparty_value(
    value: CounterpartyReference | None,
) -> dict[str, str] | None:
    if value is None:
        return None
    return {
        "external_id": value.external_id,
        "name": value.name,
        "kind": value.kind.value,
    }


def _counterparty_from_value(value: object) -> CounterpartyReference | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("Fiscal rule payment recipient is invalid.")
    return CounterpartyReference(
        external_id=value["external_id"],
        name=value["name"],
        kind=CounterpartyKind(value["kind"]),
    )
