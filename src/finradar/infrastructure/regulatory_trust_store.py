"""Core-owned Ed25519 trust store with append-only key lifecycle."""

from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timezone
from enum import Enum
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload, sessionmaker

from finradar.infrastructure.models import RegulatoryTrustedKey, RegulatoryTrustedKeyEvent


PUBLIC_KEY_BYTES = 32


class TrustedKeyStatus(str, Enum):
    TRUSTED = "trusted"
    REVOKED = "revoked"


class RegulatoryTrustError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class SqlAlchemyRegulatoryTrustStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def add_trusted_key(
        self,
        *,
        key_id: str,
        public_key: bytes,
        valid_from: datetime,
        valid_until: datetime,
        reason: str,
    ) -> None:
        _canonical_uuid(key_id)
        if len(public_key) != PUBLIC_KEY_BYTES:
            raise ValueError("Ed25519 public key must be 32 bytes.")
        valid_from = _as_utc(valid_from, "valid_from")
        valid_until = _as_utc(valid_until, "valid_until")
        if valid_until <= valid_from:
            raise ValueError("valid_until must be after valid_from.")
        _validate_reason(reason)

        encoded = base64.b64encode(public_key).decode("ascii")
        stored = RegulatoryTrustedKey(
            key_id=key_id,
            algorithm="Ed25519",
            public_key_base64=encoded,
            public_key_fingerprint=hashlib.sha256(public_key).hexdigest(),
            valid_from=valid_from,
            valid_until=valid_until,
        )
        stored.lifecycle_events.append(
            RegulatoryTrustedKeyEvent(
                sequence=1,
                status=TrustedKeyStatus.TRUSTED.value,
                reason=reason,
            )
        )
        try:
            with self._session_factory() as session:
                session.add(stored)
                session.commit()
        except IntegrityError as error:
            raise ValueError("This regulatory signing key is already registered.") from error

    def revoke_key(self, key_id: str, *, reason: str) -> None:
        _validate_reason(reason)
        with self._session_factory() as session:
            stored = self._get_key(session, key_id)
            if self._current_status(stored) is TrustedKeyStatus.REVOKED:
                raise ValueError("Regulatory signing key is already revoked.")
            stored.lifecycle_events.append(
                RegulatoryTrustedKeyEvent(
                    sequence=max(item.sequence for item in stored.lifecycle_events) + 1,
                    status=TrustedKeyStatus.REVOKED.value,
                    reason=reason,
                )
            )
            session.commit()

    def verification_key(
        self,
        key_id: str,
        *,
        signed_at: datetime,
    ) -> bytes:
        signed_at = _as_utc(signed_at, "signed_at")
        with self._session_factory() as session:
            try:
                stored = self._get_key(session, key_id)
            except LookupError as error:
                raise RegulatoryTrustError(
                    "untrusted_key",
                    "Package signing key is not trusted.",
                ) from error
            if self._current_status(stored) is TrustedKeyStatus.REVOKED:
                raise RegulatoryTrustError(
                    "revoked_key",
                    "Package signing key has been revoked.",
                )
            valid_from = _as_utc(stored.valid_from, "stored valid_from")
            valid_until = _as_utc(stored.valid_until, "stored valid_until")
            if signed_at < valid_from:
                raise RegulatoryTrustError(
                    "key_not_yet_valid",
                    "Package was signed before the key validity period.",
                )
            if signed_at >= valid_until:
                raise RegulatoryTrustError(
                    "key_expired",
                    "Package was signed after the key validity period.",
                )

            try:
                public_key = base64.b64decode(stored.public_key_base64, validate=True)
            except ValueError as error:
                raise RegulatoryTrustError(
                    "corrupt_trust_store",
                    "Trusted public key is malformed.",
                ) from error
            fingerprint = hashlib.sha256(public_key).hexdigest()
            if (
                len(public_key) != PUBLIC_KEY_BYTES
                or fingerprint != stored.public_key_fingerprint
            ):
                raise RegulatoryTrustError(
                    "corrupt_trust_store",
                    "Trusted public key integrity check failed.",
                )
            return public_key

    def lifecycle(self, key_id: str) -> tuple[TrustedKeyStatus, ...]:
        with self._session_factory() as session:
            stored = self._get_key(session, key_id)
            return tuple(
                TrustedKeyStatus(item.status)
                for item in sorted(stored.lifecycle_events, key=lambda item: item.sequence)
            )

    @staticmethod
    def _get_key(session: Session, key_id: str) -> RegulatoryTrustedKey:
        _canonical_uuid(key_id)
        stored = session.scalar(
            select(RegulatoryTrustedKey)
            .where(RegulatoryTrustedKey.key_id == key_id)
            .options(selectinload(RegulatoryTrustedKey.lifecycle_events))
        )
        if stored is None:
            raise LookupError("Regulatory signing key was not found.")
        return stored

    @staticmethod
    def _current_status(stored: RegulatoryTrustedKey) -> TrustedKeyStatus:
        if not stored.lifecycle_events:
            raise RegulatoryTrustError(
                "corrupt_trust_store",
                "Trusted key has no lifecycle history.",
            )
        latest = max(stored.lifecycle_events, key=lambda item: item.sequence)
        return TrustedKeyStatus(latest.status)


def _canonical_uuid(value: str) -> None:
    try:
        parsed = UUID(value)
    except (TypeError, ValueError) as error:
        raise ValueError("Signing key identifier must be a UUID.") from error
    if str(parsed) != value:
        raise ValueError("Signing key identifier must use canonical UUID form.")


def _as_utc(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _validate_reason(reason: str) -> None:
    if not reason.strip():
        raise ValueError("A key lifecycle reason is required.")
    if len(reason) > 500:
        raise ValueError("Key lifecycle reason is too long.")
