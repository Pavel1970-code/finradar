from dataclasses import dataclass

from finradar.domain.fiscal import PercentageFiscalRule
from finradar.domain.fiscal_consequences import FineRule, LatePaymentPenaltyRule


@dataclass(frozen=True, slots=True)
class ActiveFiscalRuleSet:
    obligation_rules: tuple[PercentageFiscalRule, ...] = ()
    penalty_rules: tuple[LatePaymentPenaltyRule, ...] = ()
    fine_rules: tuple[FineRule, ...] = ()

