"""Authenticated Core import, quarantine, replay protection, and audit."""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from finradar.infrastructure.models import (
    RegulatoryAcceptedPackage,
    RegulatoryArchiveEvent,
    RegulatoryPackageImport,
)
from finradar.infrastructure.regulatory_trust_store import (
    RegulatoryTrustError,
    SqlAlchemyRegulatoryTrustStore,
)
from finradar_contracts import (
    MAX_PACKAGE_BYTES,
    RegulatoryPackageError,
    decode_regulatory_package,
    verify_regulatory_package_signature,
)


MAX_CLOCK_SKEW = timedelta(minutes=5)


class RegulatoryInboxError(ValueError):
    """A package cannot safely cross from the Monitor into Core."""

    def __init__(self, message: str, *, code: str = "invalid_package") -> None:
        super().__init__(message)
        self.code = code


class RegulatoryImportOutcome(str, Enum):
    ACCEPTED = "accepted"
    QUARANTINED = "quarantined"
    REPLAYED = "replayed"


@dataclass(frozen=True)
class RegulatoryInboxPaths:
    root: Path
    accepted_directory: Path
    quarantine_directory: Path

    @classmethod
    def under(cls, root: Path) -> RegulatoryInboxPaths:
        resolved = root.resolve()
        return cls(
            root=resolved,
            accepted_directory=resolved / "accepted",
            quarantine_directory=resolved / "quarantine",
        )

    def create(self) -> None:
        self.accepted_directory.mkdir(parents=True, exist_ok=True)
        self.quarantine_directory.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            self.root.chmod(0o700)
            self.accepted_directory.chmod(0o700)
            self.quarantine_directory.chmod(0o700)


@dataclass(frozen=True)
class RegulatoryImportResult:
    import_id: str
    outcome: RegulatoryImportOutcome
    reason_code: str
    package_id: str | None
    signing_key_id: str | None
    archive_path: Path | None
    package: dict[str, Any] | None = None


class RegulatoryPackageImporter:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        trust_store: SqlAlchemyRegulatoryTrustStore,
        paths: RegulatoryInboxPaths,
    ) -> None:
        self._session_factory = session_factory
        self._trust_store = trust_store
        self._paths = paths

    def import_file(
        self,
        package_path: Path,
        *,
        received_at: datetime | None = None,
    ) -> RegulatoryImportResult:
        timestamp = _as_utc(received_at or datetime.now(timezone.utc))
        import_id = str(uuid4())
        try:
            raw_package, original_name = _read_bounded_file(package_path)
        except RegulatoryInboxError as error:
            return self._record_rejection(
                import_id=import_id,
                original_name=package_path.name[:255] or "unknown",
                content_hash=None,
                package_id=None,
                signing_key_id=None,
                outcome=RegulatoryImportOutcome.QUARANTINED,
                reason_code=error.code,
                reason_detail=str(error),
                received_at=timestamp,
                archive_path=None,
            )
        content_hash = hashlib.sha256(raw_package).hexdigest()
        package_id: str | None = None
        signing_key_id: str | None = None

        if package_path.suffix.casefold() != ".json":
            return self._reject(
                import_id=import_id,
                raw_package=raw_package,
                original_name=original_name,
                content_hash=content_hash,
                package_id=None,
                signing_key_id=None,
                outcome=RegulatoryImportOutcome.QUARANTINED,
                reason_code="invalid_extension",
                reason_detail="Regulatory package must be a JSON file.",
                received_at=timestamp,
            )

        try:
            package = decode_regulatory_package(raw_package)
            package_id = package["package_id"]
            signing_key_id = package["signature"]["key_id"]
            created_at = _parse_package_datetime(package["created_at"])
            expires_at = _parse_package_datetime(package["expires_at"])
            if created_at > timestamp + MAX_CLOCK_SKEW:
                raise RegulatoryInboxError(
                    "Package creation time is too far in the future.",
                    code="future_package",
                )
            if expires_at <= timestamp:
                raise RegulatoryInboxError(
                    "Regulatory package has expired.",
                    code="expired_package",
                )
            public_key = self._trust_store.verification_key(
                signing_key_id,
                signed_at=created_at,
            )
            verify_regulatory_package_signature(package, public_key)
        except RegulatoryTrustError as error:
            return self._reject(
                import_id=import_id,
                raw_package=raw_package,
                original_name=original_name,
                content_hash=content_hash,
                package_id=package_id,
                signing_key_id=signing_key_id,
                outcome=RegulatoryImportOutcome.QUARANTINED,
                reason_code=error.code,
                reason_detail=str(error),
                received_at=timestamp,
            )
        except RegulatoryInboxError as error:
            return self._reject(
                import_id=import_id,
                raw_package=raw_package,
                original_name=original_name,
                content_hash=content_hash,
                package_id=package_id,
                signing_key_id=signing_key_id,
                outcome=RegulatoryImportOutcome.QUARANTINED,
                reason_code=error.code,
                reason_detail=str(error),
                received_at=timestamp,
            )
        except RegulatoryPackageError as error:
            reason_code = (
                "invalid_signature"
                if "signature verification" in str(error)
                else "malformed_package"
            )
            return self._reject(
                import_id=import_id,
                raw_package=raw_package,
                original_name=original_name,
                content_hash=content_hash,
                package_id=package_id,
                signing_key_id=signing_key_id,
                outcome=RegulatoryImportOutcome.QUARANTINED,
                reason_code=reason_code,
                reason_detail=str(error),
                received_at=timestamp,
            )

        with self._session_factory() as session:
            replay = session.get(RegulatoryAcceptedPackage, package_id) is not None
        if replay:
            return self._reject(
                import_id=import_id,
                raw_package=raw_package,
                original_name=original_name,
                content_hash=content_hash,
                package_id=package_id,
                signing_key_id=signing_key_id,
                outcome=RegulatoryImportOutcome.REPLAYED,
                reason_code="replayed_package",
                reason_detail="Package identifier has already been accepted.",
                received_at=timestamp,
            )

        archive_path = _archive_bytes(
            self._paths,
            RegulatoryImportOutcome.ACCEPTED,
            import_id,
            raw_package,
        )
        audit = RegulatoryPackageImport(
            id=import_id,
            package_id=package_id,
            content_hash=content_hash,
            original_name=original_name,
            archive_location=_relative_archive_path(self._paths, archive_path),
            signing_key_id=signing_key_id,
            outcome=RegulatoryImportOutcome.ACCEPTED.value,
            reason_code="verified",
            reason_detail="Package structure, trust, lifetime, and signature verified.",
            received_at=timestamp,
        )
        accepted = RegulatoryAcceptedPackage(
            package_id=package_id,
            import_id=import_id,
            payload_hash=package["payload_sha256"],
            signing_key_id=signing_key_id,
        )
        try:
            with self._session_factory() as session:
                session.add(audit)
                session.flush()
                session.add(accepted)
                session.commit()
        except IntegrityError as error:
            quarantine_path = self._paths.quarantine_directory / archive_path.name
            archive_path.replace(quarantine_path)
            with self._session_factory() as session:
                accepted_concurrently = (
                    session.get(RegulatoryAcceptedPackage, package_id) is not None
                )
            if not accepted_concurrently:
                raise error
            return self._record_rejection(
                import_id=import_id,
                original_name=original_name,
                content_hash=content_hash,
                package_id=package_id,
                signing_key_id=signing_key_id,
                outcome=RegulatoryImportOutcome.REPLAYED,
                reason_code="replayed_package",
                reason_detail="Package was accepted concurrently by another importer.",
                received_at=timestamp,
                archive_path=quarantine_path,
            )

        return RegulatoryImportResult(
            import_id=import_id,
            outcome=RegulatoryImportOutcome.ACCEPTED,
            reason_code="verified",
            package_id=package_id,
            signing_key_id=signing_key_id,
            archive_path=archive_path,
            package=package,
        )

    def load_archived_bytes(self, import_id: str) -> bytes:
        with self._session_factory() as session:
            audit = session.get(RegulatoryPackageImport, import_id)
            if audit is None:
                raise LookupError("Regulatory import audit record was not found.")
            archive_location = audit.archive_location
            expected_hash = audit.content_hash
            retention_terminal = session.scalar(
                select(RegulatoryArchiveEvent.event_type)
                .where(
                    RegulatoryArchiveEvent.import_id == import_id,
                    RegulatoryArchiveEvent.event_type.in_(("deleted", "missing")),
                )
                .limit(1)
            )
        if retention_terminal:
            raise RegulatoryInboxError(
                "Archived package bytes are no longer available.",
                code="archive_retention_deleted",
            )
        if archive_location is None or expected_hash is None:
            raise RegulatoryInboxError(
                "Rejected package has no archived bytes.",
                code="archive_unavailable",
            )
        try:
            archive_path = (self._paths.root / archive_location).resolve(strict=True)
        except FileNotFoundError as error:
            raise RegulatoryInboxError(
                "Archived package bytes are no longer available.",
                code="archive_missing",
            ) from error
        if not archive_path.is_relative_to(self._paths.root):
            raise RegulatoryInboxError(
                "Archived package path escaped the Core archive.",
                code="corrupt_audit",
            )
        raw_package = archive_path.read_bytes()
        actual_hash = hashlib.sha256(raw_package).hexdigest()
        if actual_hash != expected_hash:
            raise RegulatoryInboxError(
                "Archived package integrity check failed.",
                code="archive_tampered",
            )
        return raw_package

    def _reject(
        self,
        *,
        import_id: str,
        raw_package: bytes,
        original_name: str,
        content_hash: str | None,
        package_id: str | None,
        signing_key_id: str | None,
        outcome: RegulatoryImportOutcome,
        reason_code: str,
        reason_detail: str,
        received_at: datetime,
    ) -> RegulatoryImportResult:
        archive_path = _archive_bytes(self._paths, outcome, import_id, raw_package)
        return self._record_rejection(
            import_id=import_id,
            original_name=original_name,
            content_hash=content_hash,
            package_id=package_id,
            signing_key_id=signing_key_id,
            outcome=outcome,
            reason_code=reason_code,
            reason_detail=reason_detail,
            received_at=received_at,
            archive_path=archive_path,
        )

    def _record_rejection(
        self,
        *,
        import_id: str,
        original_name: str,
        content_hash: str | None,
        package_id: str | None,
        signing_key_id: str | None,
        outcome: RegulatoryImportOutcome,
        reason_code: str,
        reason_detail: str,
        received_at: datetime,
        archive_path: Path | None,
    ) -> RegulatoryImportResult:
        with self._session_factory() as session:
            session.add(
                RegulatoryPackageImport(
                    id=import_id,
                    package_id=package_id,
                    content_hash=content_hash,
                    original_name=original_name,
                    archive_location=(
                        _relative_archive_path(self._paths, archive_path)
                        if archive_path is not None
                        else None
                    ),
                    signing_key_id=signing_key_id,
                    outcome=outcome.value,
                    reason_code=reason_code,
                    reason_detail=reason_detail[:500],
                    received_at=received_at,
                )
            )
            session.commit()
        return RegulatoryImportResult(
            import_id=import_id,
            outcome=outcome,
            reason_code=reason_code,
            package_id=package_id,
            signing_key_id=signing_key_id,
            archive_path=archive_path,
        )


def parse_untrusted_regulatory_package_file(package_path: Path) -> dict[str, Any]:
    """Parse structure only; use RegulatoryPackageImporter for any trusted import."""
    raw_package, _ = _read_bounded_file(package_path)
    if package_path.suffix.casefold() != ".json":
        raise RegulatoryInboxError("Regulatory package must be a JSON file.")
    try:
        return decode_regulatory_package(raw_package)
    except RegulatoryPackageError as error:
        raise RegulatoryInboxError(str(error)) from error


def _read_bounded_file(package_path: Path) -> tuple[bytes, str]:
    if package_path.is_symlink():
        raise RegulatoryInboxError(
            "Regulatory package cannot be a symbolic link.",
            code="symbolic_link",
        )
    try:
        path = package_path.resolve(strict=True)
    except FileNotFoundError as error:
        raise RegulatoryInboxError("Regulatory package file was not found.") from error
    if not path.is_file():
        raise RegulatoryInboxError("Regulatory package must be a regular file.")
    size = path.stat().st_size
    if size > MAX_PACKAGE_BYTES:
        raise RegulatoryInboxError(
            "Regulatory package exceeds the maximum allowed size.",
            code="oversized_package",
        )
    return path.read_bytes(), path.name[:255]


def _archive_bytes(
    paths: RegulatoryInboxPaths,
    outcome: RegulatoryImportOutcome,
    import_id: str,
    raw_package: bytes,
) -> Path:
    paths.create()
    directory = (
        paths.accepted_directory
        if outcome is RegulatoryImportOutcome.ACCEPTED
        else paths.quarantine_directory
    )
    destination = directory / f"{import_id}.json"
    descriptor, temporary_name = tempfile.mkstemp(
        dir=directory,
        prefix=f".{import_id}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        if os.name != "nt":
            temporary_path.chmod(0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw_package)
            stream.flush()
            os.fsync(stream.fileno())
        temporary_path.replace(destination)
        if os.name != "nt":
            destination.chmod(0o400)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
    return destination


def _relative_archive_path(paths: RegulatoryInboxPaths, archive_path: Path) -> str:
    return archive_path.relative_to(paths.root).as_posix()


def _parse_package_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise RegulatoryInboxError("Package datetime is malformed.")
    try:
        return _as_utc(datetime.fromisoformat(value))
    except ValueError as error:
        raise RegulatoryInboxError("Package datetime is malformed.") from error


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise RegulatoryInboxError("Datetime must include a timezone.")
    return value.astimezone(timezone.utc)
