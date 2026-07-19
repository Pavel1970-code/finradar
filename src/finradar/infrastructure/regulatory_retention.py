"""Controlled retention for rejected regulatory-package archives."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from finradar.infrastructure.models import (
    RegulatoryArchiveEvent,
    RegulatoryPackageImport,
)
from finradar.infrastructure.regulatory_inbox import (
    RegulatoryImportOutcome,
    RegulatoryInboxPaths,
)


class ArchiveEventType(str, Enum):
    DELETION_STARTED = "deletion_started"
    DELETED = "deleted"
    MISSING = "missing"
    DELETION_BLOCKED = "deletion_blocked"
    DELETION_FAILED = "deletion_failed"


TERMINAL_EVENTS = {
    ArchiveEventType.DELETED.value,
    ArchiveEventType.MISSING.value,
    ArchiveEventType.DELETION_BLOCKED.value,
}


@dataclass(frozen=True)
class RegulatoryRetentionPolicy:
    quarantined_days: int = 30
    replayed_days: int = 7

    def __post_init__(self) -> None:
        if self.quarantined_days < 1 or self.replayed_days < 1:
            raise ValueError("Retention periods must be at least one day.")


@dataclass(frozen=True)
class RegulatoryRetentionReport:
    examined: int
    deleted: int
    missing: int
    blocked: int
    failed: int


class RegulatoryArchiveRetention:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        paths: RegulatoryInboxPaths,
        policy: RegulatoryRetentionPolicy | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._paths = paths
        self._policy = policy or RegulatoryRetentionPolicy()

    def enforce(self, *, at_time: datetime | None = None) -> RegulatoryRetentionReport:
        timestamp = _as_utc(at_time or datetime.now(timezone.utc))
        oldest_cutoff = timestamp - timedelta(
            days=min(self._policy.quarantined_days, self._policy.replayed_days)
        )
        with self._session_factory() as session:
            candidates = tuple(
                session.scalars(
                    select(RegulatoryPackageImport)
                    .where(
                        RegulatoryPackageImport.outcome.in_(
                            (
                                RegulatoryImportOutcome.QUARANTINED.value,
                                RegulatoryImportOutcome.REPLAYED.value,
                            )
                        ),
                        RegulatoryPackageImport.received_at <= oldest_cutoff,
                        RegulatoryPackageImport.archive_location.is_not(None),
                    )
                    .order_by(RegulatoryPackageImport.received_at)
                )
            )

        totals = {
            "deleted": 0,
            "missing": 0,
            "blocked": 0,
            "failed": 0,
        }
        examined = 0
        for audit in candidates:
            retention_days = (
                self._policy.replayed_days
                if audit.outcome == RegulatoryImportOutcome.REPLAYED.value
                else self._policy.quarantined_days
            )
            if _as_utc(audit.received_at) > timestamp - timedelta(days=retention_days):
                continue
            if self._has_terminal_event(audit.id):
                continue
            examined += 1
            result = self._delete_archive(audit)
            totals[result] += 1

        return RegulatoryRetentionReport(examined=examined, **totals)

    def _delete_archive(self, audit: RegulatoryPackageImport) -> str:
        try:
            archive_path = self._safe_quarantine_path(audit.archive_location)
        except ValueError as error:
            self._event(audit.id, ArchiveEventType.DELETION_BLOCKED, str(error))
            return "blocked"
        if not archive_path.exists():
            self._event(
                audit.id,
                ArchiveEventType.MISSING,
                "Archive was already absent when retention ran.",
            )
            return "missing"
        if archive_path.is_symlink() or not archive_path.is_file():
            self._event(
                audit.id,
                ArchiveEventType.DELETION_BLOCKED,
                "Archive is not a regular file.",
            )
            return "blocked"
        actual_hash = hashlib.sha256(archive_path.read_bytes()).hexdigest()
        if audit.content_hash is None or actual_hash != audit.content_hash:
            self._event(
                audit.id,
                ArchiveEventType.DELETION_BLOCKED,
                "Archive integrity check failed; evidence was preserved.",
            )
            return "blocked"

        if not self._has_event(audit.id, ArchiveEventType.DELETION_STARTED):
            self._event(
                audit.id,
                ArchiveEventType.DELETION_STARTED,
                "Archive passed retention and integrity checks.",
            )
        try:
            archive_path.unlink()
        except OSError as error:
            self._event(
                audit.id,
                ArchiveEventType.DELETION_FAILED,
                f"Archive deletion failed: {type(error).__name__}.",
            )
            return "failed"
        self._event(
            audit.id,
            ArchiveEventType.DELETED,
            "Rejected archive deleted under the configured retention policy.",
        )
        return "deleted"

    def _safe_quarantine_path(self, archive_location: str | None) -> Path:
        if not archive_location:
            raise ValueError("Archive location is missing.")
        relative = Path(archive_location)
        if relative.is_absolute() or not relative.parts or relative.parts[0] != "quarantine":
            raise ValueError("Archive location is outside quarantine.")
        candidate = self._paths.root / relative
        resolved = candidate.resolve(strict=False)
        quarantine = self._paths.quarantine_directory.resolve()
        if not resolved.is_relative_to(quarantine):
            raise ValueError("Archive location escaped quarantine.")
        return candidate

    def _has_terminal_event(self, import_id: str) -> bool:
        with self._session_factory() as session:
            event_type = session.scalar(
                select(RegulatoryArchiveEvent.event_type)
                .where(
                    RegulatoryArchiveEvent.import_id == import_id,
                    RegulatoryArchiveEvent.event_type.in_(TERMINAL_EVENTS),
                )
                .limit(1)
            )
        return event_type is not None

    def _has_event(self, import_id: str, event_type: ArchiveEventType) -> bool:
        with self._session_factory() as session:
            existing = session.scalar(
                select(RegulatoryArchiveEvent.id)
                .where(
                    RegulatoryArchiveEvent.import_id == import_id,
                    RegulatoryArchiveEvent.event_type == event_type.value,
                )
                .limit(1)
            )
        return existing is not None

    def _event(
        self,
        import_id: str,
        event_type: ArchiveEventType,
        reason: str,
    ) -> None:
        with self._session_factory() as session:
            session.add(
                RegulatoryArchiveEvent(
                    import_id=import_id,
                    event_type=event_type.value,
                    reason=reason[:500],
                )
            )
            session.commit()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
