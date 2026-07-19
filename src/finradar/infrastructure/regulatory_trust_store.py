"""Core-owned Ed25519 trust store with append-only key lifecycle."""

from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timedelta, timezone
from enum import Enum
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload, sessionmaker

from finradar.infrastructure.models import (
    RegulatoryKeyRotation,
    RegulatoryTrustBootstrap,
    RegulatoryTrustedKey,
    RegulatoryTrustedKeyEvent,
)
from finradar_contracts import (
    TrustRecordError,
    decode_rotation_record,
    decode_trust_record,
    encode_rotation_record,
    encode_trust_record,
    verify_rotation_record,
)


PUBLIC_KEY_BYTES = 32
MAX_CLOCK_SKEW = timedelta(minutes=5)


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

    def bootstrap_initial_key(
        self,
        *,
        public_key_record: dict[str, object],
        source: str,
        reason: str,
        received_at: datetime | None = None,
    ) -> None:
        if not source.strip() or len(source) > 200:
            raise ValueError("A valid bootstrap source is required.")
        _validate_reason(reason)
        encoded_record = encode_trust_record(public_key_record)
        record = decode_trust_record(encoded_record)
        timestamp = _as_utc(received_at or datetime.now(timezone.utc), "received_at")
        valid_from = _as_utc(datetime.fromisoformat(record["valid_from"]), "valid_from")
        valid_until = _as_utc(
            datetime.fromisoformat(record["valid_until"]),
            "valid_until",
        )
        try:
            with self._session_factory() as session:
                existing_keys = session.scalar(
                    select(func.count()).select_from(RegulatoryTrustedKey)
                )
                bootstrap = session.get(RegulatoryTrustBootstrap, 1)
                record_hash = hashlib.sha256(encoded_record).hexdigest()
                if bootstrap is not None:
                    if (
                        bootstrap.key_id == record["key_id"]
                        and bootstrap.record_hash == record_hash
                        and session.get(RegulatoryTrustedKey, bootstrap.key_id) is not None
                    ):
                        return
                    raise ValueError("Regulatory trust has already been bootstrapped.")
                if existing_keys:
                    raise ValueError(
                        "Trusted keys exist without a valid bootstrap record."
                    )
                if valid_from > timestamp + MAX_CLOCK_SKEW or valid_until <= timestamp:
                    raise RegulatoryTrustError(
                        "invalid_bootstrap_lifetime",
                        "Initial signing key is not currently valid.",
                    )
                stored = self._stored_key(record, reason=reason)
                session.add(stored)
                session.flush()
                session.add(
                    RegulatoryTrustBootstrap(
                        singleton_id=1,
                        key_id=record["key_id"],
                        record_hash=record_hash,
                        source=source.strip(),
                    )
                )
                session.commit()
        except IntegrityError as error:
            raise ValueError("Regulatory trust bootstrap already exists.") from error

    def apply_rotation(
        self,
        rotation_record: dict[str, object],
        *,
        received_at: datetime | None = None,
    ) -> str:
        timestamp = _as_utc(received_at or datetime.now(timezone.utc), "received_at")
        encoded_rotation = encode_rotation_record(rotation_record)
        validated = decode_rotation_record(encoded_rotation)
        issued_at = _as_utc(
            datetime.fromisoformat(validated["issued_at"]),
            "issued_at",
        )
        previous_key_id = validated["previous_key_id"]
        record = verify_rotation_record(
            validated,
            self.verification_key(
                previous_key_id,
                signed_at=issued_at,
            ),
        )
        expires_at = _as_utc(datetime.fromisoformat(record["expires_at"]), "expires_at")
        if issued_at > timestamp + MAX_CLOCK_SKEW:
            raise RegulatoryTrustError("future_rotation", "Rotation record is from the future.")
        if expires_at <= timestamp:
            raise RegulatoryTrustError("expired_rotation", "Rotation record has expired.")
        if record["new_key"]["key_id"] == record["previous_key_id"]:
            raise RegulatoryTrustError("invalid_rotation", "Rotation must introduce a new key.")

        try:
            with self._session_factory() as session:
                if session.get(RegulatoryTrustBootstrap, 1) is None:
                    raise RegulatoryTrustError(
                        "missing_bootstrap", "Initial trust has not been bootstrapped."
                    )
                if session.get(RegulatoryKeyRotation, record["rotation_id"]) is not None:
                    raise RegulatoryTrustError(
                        "replayed_rotation", "Rotation record has already been applied."
                    )
                previous = self._get_key(session, previous_key_id)
                if self._current_status(previous) is TrustedKeyStatus.REVOKED:
                    raise RegulatoryTrustError(
                        "revoked_key", "Rotation signer has been revoked."
                    )
                stored = self._stored_key(
                    record["new_key"],
                    reason=f"Authorized by rotation {record['rotation_id']}.",
                )
                session.add(stored)
                session.flush()
                session.add(
                    RegulatoryKeyRotation(
                        rotation_id=record["rotation_id"],
                        previous_key_id=previous_key_id,
                        new_key_id=record["new_key"]["key_id"],
                        content_hash=hashlib.sha256(encoded_rotation).hexdigest(),
                        issued_at=issued_at,
                    )
                )
                session.commit()
        except IntegrityError as error:
            raise RegulatoryTrustError(
                "invalid_rotation", "Rotation key or identifier already exists."
            ) from error
        return record["new_key"]["key_id"]

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
    def _stored_key(
        record: dict[str, object],
        *,
        reason: str,
    ) -> RegulatoryTrustedKey:
        try:
            public_key = base64.b64decode(str(record["public_key_base64"]), validate=True)
        except ValueError as error:
            raise TrustRecordError("public key is malformed") from error
        stored = RegulatoryTrustedKey(
            key_id=str(record["key_id"]),
            algorithm=str(record["algorithm"]),
            public_key_base64=str(record["public_key_base64"]),
            public_key_fingerprint=str(record["public_key_fingerprint"]),
            valid_from=datetime.fromisoformat(str(record["valid_from"])),
            valid_until=datetime.fromisoformat(str(record["valid_until"])),
        )
        if len(public_key) != PUBLIC_KEY_BYTES:
            raise TrustRecordError("public key must be 32 bytes")
        stored.lifecycle_events.append(
            RegulatoryTrustedKeyEvent(
                sequence=1,
                status=TrustedKeyStatus.TRUSTED.value,
                reason=reason,
            )
        )
        return stored

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
