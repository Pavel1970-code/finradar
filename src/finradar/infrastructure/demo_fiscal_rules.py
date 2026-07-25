from __future__ import annotations

from finradar.application.fiscal_rules import ActiveFiscalRuleSet
from finradar.domain.fiscal import FiscalRuleStatus
from finradar.infrastructure.fiscal_rule_codec import RuleDefinition, with_rule_status
from finradar.infrastructure.fiscal_rule_registry import SqlAlchemyFiscalRuleRegistry


_NEXT_STATUS = {
    FiscalRuleStatus.CANDIDATE: FiscalRuleStatus.VALIDATED,
    FiscalRuleStatus.VALIDATED: FiscalRuleStatus.REVIEWED,
    FiscalRuleStatus.REVIEWED: FiscalRuleStatus.ACTIVE,
}


class DemoFiscalRuleBootstrapper:
    """Provisions bundled scenario rules through the audited lifecycle."""

    def __init__(self, registry: SqlAlchemyFiscalRuleRegistry) -> None:
        self._registry = registry

    def ensure(self, rules: ActiveFiscalRuleSet) -> ActiveFiscalRuleSet:
        for rule in (
            *rules.obligation_rules,
            *rules.penalty_rules,
            *rules.fine_rules,
        ):
            self._ensure_rule(rule)
        return self._registry.load_active_ruleset()

    def _ensure_rule(self, rule: RuleDefinition) -> None:
        try:
            lifecycle = self._registry.lifecycle(rule.rule_id, rule.version)
        except LookupError:
            self._registry.register_candidate(
                with_rule_status(rule, FiscalRuleStatus.CANDIDATE),
                reason=(
                    "Bundled MVP scenario rule; activation is limited to "
                    "deterministic prototype scenarios."
                ),
            )
            lifecycle = (FiscalRuleStatus.CANDIDATE,)

        current = lifecycle[-1]
        if current is FiscalRuleStatus.SUPERSEDED:
            return
        while current is not FiscalRuleStatus.ACTIVE:
            next_status = _NEXT_STATUS.get(current)
            if next_status is None:
                raise ValueError("Demo fiscal rule has an unsupported lifecycle state.")
            self._registry.transition(
                rule.rule_id,
                rule.version,
                next_status,
                reason=(
                    "Approved only for the bundled prototype scenario; not "
                    "approved for real company calculations."
                ),
            )
            current = next_status
