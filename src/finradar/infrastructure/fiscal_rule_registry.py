from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload, sessionmaker

from finradar.application.fiscal_rules import ActiveFiscalRuleSet
from finradar.domain.fiscal import FiscalRuleStatus
from finradar.domain.fiscal import PercentageFiscalRule
from finradar.domain.fiscal_consequences import FineRule, LatePaymentPenaltyRule
from finradar.infrastructure.fiscal_rule_codec import (
    RuleDefinition,
    decode_rule,
    encode_rule,
)
from finradar.infrastructure.models import (
    FiscalRuleLifecycleEvent,
    FiscalRuleVersion,
)


ALLOWED_TRANSITIONS = {
    FiscalRuleStatus.CANDIDATE: {FiscalRuleStatus.VALIDATED},
    FiscalRuleStatus.VALIDATED: {FiscalRuleStatus.REVIEWED},
    FiscalRuleStatus.REVIEWED: {FiscalRuleStatus.ACTIVE},
    FiscalRuleStatus.ACTIVE: {FiscalRuleStatus.SUPERSEDED},
    FiscalRuleStatus.SUPERSEDED: set(),
}


class SqlAlchemyFiscalRuleRegistry:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def register_candidate(self, rule: RuleDefinition, *, reason: str) -> str:
        if rule.status is not FiscalRuleStatus.CANDIDATE:
            raise ValueError("New fiscal rules must be registered as candidates.")
        if not reason.strip():
            raise ValueError("A lifecycle reason is required.")

        rule_type, content_json = encode_rule(rule)
        stored = FiscalRuleVersion(
            rule_id=rule.rule_id,
            version=rule.version,
            rule_type=rule_type,
            content_json=content_json,
            content_hash=sha256(content_json.encode("utf-8")).hexdigest(),
            source_reference=rule.source_reference,
        )
        stored.lifecycle_events.append(
            FiscalRuleLifecycleEvent(
                sequence=1,
                status=FiscalRuleStatus.CANDIDATE.value,
                reason=reason,
            )
        )
        try:
            with self._session_factory() as session:
                session.add(stored)
                session.commit()
                return stored.id
        except IntegrityError as error:
            raise ValueError("This fiscal rule version already exists.") from error

    def transition(
        self,
        rule_id: str,
        version: int,
        new_status: FiscalRuleStatus,
        *,
        reason: str,
    ) -> None:
        if not reason.strip():
            raise ValueError("A lifecycle reason is required.")

        with self._session_factory() as session:
            stored = self._get_version(session, rule_id, version)
            current = self._current_status(stored)
            if new_status not in ALLOWED_TRANSITIONS[current]:
                raise ValueError(
                    f"Invalid fiscal rule transition: {current.value} -> "
                    f"{new_status.value}."
                )

            if new_status is FiscalRuleStatus.ACTIVE:
                versions = tuple(
                    session.scalars(
                        select(FiscalRuleVersion)
                        .where(
                            FiscalRuleVersion.rule_id == rule_id,
                            FiscalRuleVersion.id != stored.id,
                        )
                        .options(selectinload(FiscalRuleVersion.lifecycle_events))
                    )
                )
                for other in versions:
                    if self._current_status(other) is FiscalRuleStatus.ACTIVE:
                        self._append_status(
                            other,
                            FiscalRuleStatus.SUPERSEDED,
                            reason=f"Superseded by version {version}: {reason}",
                        )

            self._append_status(stored, new_status, reason=reason)
            session.commit()

    def load_active(self) -> tuple[RuleDefinition, ...]:
        with self._session_factory() as session:
            versions = tuple(
                session.scalars(
                    select(FiscalRuleVersion)
                    .options(selectinload(FiscalRuleVersion.lifecycle_events))
                    .order_by(FiscalRuleVersion.rule_id, FiscalRuleVersion.version)
                )
            )
            active: list[RuleDefinition] = []
            for stored in versions:
                status = self._current_status(stored)
                if status is FiscalRuleStatus.ACTIVE:
                    self._verify_hash(stored)
                    active.append(decode_rule(stored.content_json, status=status))
            return tuple(active)

    def load_active_ruleset(self) -> ActiveFiscalRuleSet:
        active = self.load_active()
        return ActiveFiscalRuleSet(
            obligation_rules=tuple(
                item for item in active if isinstance(item, PercentageFiscalRule)
            ),
            penalty_rules=tuple(
                item for item in active if isinstance(item, LatePaymentPenaltyRule)
            ),
            fine_rules=tuple(item for item in active if isinstance(item, FineRule)),
        )

    def lifecycle(self, rule_id: str, version: int) -> tuple[FiscalRuleStatus, ...]:
        with self._session_factory() as session:
            stored = self._get_version(session, rule_id, version)
            return tuple(
                FiscalRuleStatus(item.status)
                for item in sorted(stored.lifecycle_events, key=lambda item: item.sequence)
            )

    def _get_version(
        self,
        session: Session,
        rule_id: str,
        version: int,
    ) -> FiscalRuleVersion:
        stored = session.scalar(
            select(FiscalRuleVersion)
            .where(
                FiscalRuleVersion.rule_id == rule_id,
                FiscalRuleVersion.version == version,
            )
            .options(selectinload(FiscalRuleVersion.lifecycle_events))
        )
        if stored is None:
            raise LookupError("Fiscal rule version was not found.")
        return stored

    @staticmethod
    def _current_status(stored: FiscalRuleVersion) -> FiscalRuleStatus:
        if not stored.lifecycle_events:
            raise ValueError("Fiscal rule has no lifecycle history.")
        latest = max(stored.lifecycle_events, key=lambda item: item.sequence)
        return FiscalRuleStatus(latest.status)

    @staticmethod
    def _append_status(
        stored: FiscalRuleVersion,
        status: FiscalRuleStatus,
        *,
        reason: str,
    ) -> None:
        next_sequence = max(
            (item.sequence for item in stored.lifecycle_events),
            default=0,
        ) + 1
        stored.lifecycle_events.append(
            FiscalRuleLifecycleEvent(
                sequence=next_sequence,
                status=status.value,
                reason=reason,
            )
        )

    @staticmethod
    def _verify_hash(stored: FiscalRuleVersion) -> None:
        actual = sha256(stored.content_json.encode("utf-8")).hexdigest()
        if actual != stored.content_hash:
            raise ValueError("Fiscal rule integrity check failed.")
