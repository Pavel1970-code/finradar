from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal
from importlib import resources
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from finradar.domain.georgia_payroll import (
    GeorgiaPayrollRules,
    PayrollLegalSource,
    StateCofinancingTier,
)


PAYROLL_RULE_SCHEMA_VERSION = 1


class GeorgiaPayrollRuleError(ValueError):
    """Raised when the bundled Georgian payroll rule set is invalid."""


class _ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _SourceData(_ContractModel):
    source_id: str
    title: str
    url: str
    provisions: tuple[str, ...]


class _TierData(_ContractModel):
    lower_bound: Decimal = Field(ge=0)
    upper_bound: Decimal | None = Field(default=None, gt=0)
    rate: Decimal = Field(ge=0, le=1)


class _RulePayload(_ContractModel):
    verified_on: date
    standard_income_tax_rate: Decimal = Field(ge=0, le=1)
    employee_pension_rate: Decimal = Field(ge=0, le=1)
    employer_pension_rate: Decimal = Field(ge=0, le=1)
    state_cofinancing_tiers: tuple[_TierData, ...]
    payroll_declaration_day: int = Field(ge=1, le=28)
    sources: tuple[_SourceData, ...]


class _RuleEnvelope(_ContractModel):
    schema_version: int
    rule_set_id: str
    rule_set_version: int = Field(ge=1)
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    payload: _RulePayload


class GeorgiaPayrollRuleRepository:
    def __init__(self, resource_directory: Path | None = None) -> None:
        self._resource_directory = resource_directory

    def load(self, *, version: int = 1) -> GeorgiaPayrollRules:
        filename = f"georgia_payroll_rules_v{version}.json"
        try:
            content = self._read_text(filename)
        except FileNotFoundError as error:
            raise GeorgiaPayrollRuleError(
                f"Unknown Georgian payroll rule version: {version}."
            ) from error
        try:
            raw = json.loads(content)
            envelope = _RuleEnvelope.model_validate(raw)
        except (json.JSONDecodeError, TypeError, ValueError) as error:
            raise GeorgiaPayrollRuleError(
                "Georgian payroll rule contract is invalid."
            ) from error
        if envelope.schema_version != PAYROLL_RULE_SCHEMA_VERSION:
            raise GeorgiaPayrollRuleError(
                "Unsupported Georgian payroll rule schema."
            )
        if envelope.rule_set_id != "georgia-payroll":
            raise GeorgiaPayrollRuleError("Georgian payroll rule-set ID is invalid.")
        if envelope.rule_set_version != version:
            raise GeorgiaPayrollRuleError(
                "Georgian payroll rule version does not match its filename."
            )
        if _payload_hash(raw.get("payload")) != envelope.payload_sha256:
            raise GeorgiaPayrollRuleError(
                "Georgian payroll rule integrity check failed."
            )
        payload = envelope.payload
        tiers = tuple(
            StateCofinancingTier(**item.model_dump())
            for item in payload.state_cofinancing_tiers
        )
        _validate_tiers(tiers)
        return GeorgiaPayrollRules(
            version=envelope.rule_set_version,
            verified_on=payload.verified_on,
            standard_income_tax_rate=payload.standard_income_tax_rate,
            employee_pension_rate=payload.employee_pension_rate,
            employer_pension_rate=payload.employer_pension_rate,
            state_cofinancing_tiers=tiers,
            payroll_declaration_day=payload.payroll_declaration_day,
            sources=tuple(
                PayrollLegalSource(**item.model_dump()) for item in payload.sources
            ),
        )

    def _read_text(self, filename: str) -> str:
        if self._resource_directory is not None:
            return (self._resource_directory / filename).read_text(encoding="utf-8")
        rule_files = resources.files("finradar.regulatory.rules")
        return rule_files.joinpath(filename).read_text(encoding="utf-8")


def _validate_tiers(tiers: tuple[StateCofinancingTier, ...]) -> None:
    if not tiers or tiers[0].lower_bound != Decimal("0"):
        raise GeorgiaPayrollRuleError(
            "State co-financing tiers must start at zero."
        )
    previous_upper: Decimal | None = Decimal("0")
    for index, tier in enumerate(tiers):
        if previous_upper is None or tier.lower_bound != previous_upper:
            raise GeorgiaPayrollRuleError(
                "State co-financing tiers must be contiguous."
            )
        if tier.upper_bound is not None and tier.upper_bound <= tier.lower_bound:
            raise GeorgiaPayrollRuleError(
                "State co-financing tier bounds are invalid."
            )
        if tier.upper_bound is None and index != len(tiers) - 1:
            raise GeorgiaPayrollRuleError(
                "Only the last state co-financing tier may be open-ended."
            )
        previous_upper = tier.upper_bound
    if tiers[-1].upper_bound is not None:
        raise GeorgiaPayrollRuleError(
            "State co-financing tiers must cover the open-ended range."
        )


def _payload_hash(payload: object) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
