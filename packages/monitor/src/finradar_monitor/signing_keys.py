"""Private Ed25519 key storage owned only by the Monitor identity."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

from finradar_contracts import (
    build_public_key_record,
    encode_trust_record,
    generate_private_key_bytes,
    public_key_bytes,
)


KEY_METADATA_FIELDS = {
    "algorithm",
    "key_id",
    "public_key_base64",
    "public_key_fingerprint",
    "valid_from",
    "valid_until",
}
MAX_KEY_LIFETIME = timedelta(days=366)


class MonitorSigningKeyError(ValueError):
    """The Monitor signing key store is missing, unsafe, or inconsistent."""


@dataclass(frozen=True)
class MonitorSigningKey:
    key_id: str
    private_key: bytes
    public_key: bytes
    valid_from: datetime
    valid_until: datetime

    @property
    def public_key_fingerprint(self) -> str:
        return hashlib.sha256(self.public_key).hexdigest()

    def public_record(self) -> dict[str, object]:
        return build_public_key_record(
            key_id=self.key_id,
            public_key=self.public_key,
            valid_from=self.valid_from,
            valid_until=self.valid_until,
        )


class MonitorSigningKeyStore:
    def __init__(self, directory: Path) -> None:
        self._directory = directory.resolve()
        self._active_key_path = self._directory / "active-key-id"

    def initialize(self) -> None:
        self._directory.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            self._directory.chmod(0o700)

    def initialize_bootstrap_key(
        self,
        public_record_path: Path,
        *,
        at_time: datetime | None = None,
    ) -> MonitorSigningKey:
        """Create the first key once, then idempotently re-export its public record."""
        timestamp = _aware_datetime(at_time or datetime.now(timezone.utc), "at_time")
        self.initialize()
        if self._active_key_path.exists():
            key = self.load_active(at_time=timestamp)
        else:
            key_artifacts = tuple(self._directory.glob("*.ed25519-key")) + tuple(
                self._directory.glob("*.json")
            )
            if key_artifacts:
                raise MonitorSigningKeyError(
                    "inactive signing-key artifacts require operator recovery"
                )
            key = self.create_key(
                valid_from=timestamp - timedelta(minutes=5),
                valid_until=timestamp + timedelta(days=365),
            )
            self.activate_key(key.key_id, at_time=timestamp)

        destination = public_record_path.resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        self._write_bytes_atomic_to(destination, encode_trust_record(key.public_record()))
        return key

    def create_key(
        self,
        *,
        valid_from: datetime,
        valid_until: datetime,
        key_id: str | None = None,
    ) -> MonitorSigningKey:
        valid_from = _aware_datetime(valid_from, "valid_from")
        valid_until = _aware_datetime(valid_until, "valid_until")
        if valid_until <= valid_from:
            raise MonitorSigningKeyError("valid_until must be after valid_from")
        if valid_until - valid_from > MAX_KEY_LIFETIME:
            raise MonitorSigningKeyError("signing key lifetime exceeds 366 days")
        resolved_key_id = key_id or str(uuid4())
        _canonical_uuid(resolved_key_id)

        self.initialize()
        private_key = generate_private_key_bytes()
        public_key = public_key_bytes(private_key)
        stored = MonitorSigningKey(
            key_id=resolved_key_id,
            private_key=private_key,
            public_key=public_key,
            valid_from=valid_from,
            valid_until=valid_until,
        )
        key_path = self._private_key_path(resolved_key_id)
        descriptor = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(private_key)
                stream.flush()
                os.fsync(stream.fileno())
            self._write_json_atomic(
                self._metadata_path(resolved_key_id),
                {
                    "algorithm": "Ed25519",
                    "key_id": resolved_key_id,
                    "public_key_base64": base64.b64encode(public_key).decode("ascii"),
                    "public_key_fingerprint": stored.public_key_fingerprint,
                    "valid_from": valid_from.isoformat(),
                    "valid_until": valid_until.isoformat(),
                },
            )
        except BaseException:
            key_path.unlink(missing_ok=True)
            raise
        return stored

    def activate_key(self, key_id: str, *, at_time: datetime | None = None) -> None:
        key = self.load_key(key_id)
        timestamp = _aware_datetime(at_time or datetime.now(timezone.utc), "at_time")
        if not key.valid_from <= timestamp < key.valid_until:
            raise MonitorSigningKeyError("signing key is not valid at activation time")
        self._write_bytes_atomic(self._active_key_path, key_id.encode("ascii"))

    def load_active(self, *, at_time: datetime | None = None) -> MonitorSigningKey:
        try:
            key_id = self._active_key_path.read_text(encoding="ascii")
        except FileNotFoundError as error:
            raise MonitorSigningKeyError("no active Monitor signing key") from error
        if key_id != key_id.strip():
            raise MonitorSigningKeyError("active signing key identifier is malformed")
        key = self.load_key(key_id)
        timestamp = _aware_datetime(at_time or datetime.now(timezone.utc), "at_time")
        if not key.valid_from <= timestamp < key.valid_until:
            raise MonitorSigningKeyError("active Monitor signing key is outside its validity")
        return key

    def load_key(self, key_id: str) -> MonitorSigningKey:
        _canonical_uuid(key_id)
        try:
            metadata = json.loads(self._metadata_path(key_id).read_text(encoding="utf-8"))
            private_key = self._private_key_path(key_id).read_bytes()
        except (FileNotFoundError, json.JSONDecodeError) as error:
            raise MonitorSigningKeyError("Monitor signing key is missing or malformed") from error
        if not isinstance(metadata, dict) or set(metadata) != KEY_METADATA_FIELDS:
            raise MonitorSigningKeyError("Monitor signing key metadata has invalid fields")
        if metadata["algorithm"] != "Ed25519" or metadata["key_id"] != key_id:
            raise MonitorSigningKeyError("Monitor signing key metadata is inconsistent")
        if os.name != "nt" and self._private_key_path(key_id).stat().st_mode & 0o077:
            raise MonitorSigningKeyError("Monitor private key permissions are too broad")

        derived_public_key = public_key_bytes(private_key)
        try:
            stored_public_key = base64.b64decode(
                metadata["public_key_base64"],
                validate=True,
            )
        except (TypeError, ValueError) as error:
            raise MonitorSigningKeyError("Monitor public key metadata is malformed") from error
        fingerprint = hashlib.sha256(derived_public_key).hexdigest()
        if stored_public_key != derived_public_key or metadata["public_key_fingerprint"] != fingerprint:
            raise MonitorSigningKeyError("Monitor signing key integrity check failed")
        valid_from = _parse_datetime(metadata["valid_from"], "valid_from")
        valid_until = _parse_datetime(metadata["valid_until"], "valid_until")
        if valid_until <= valid_from or valid_until - valid_from > MAX_KEY_LIFETIME:
            raise MonitorSigningKeyError("Monitor signing key validity is inconsistent")
        return MonitorSigningKey(
            key_id=key_id,
            private_key=private_key,
            public_key=derived_public_key,
            valid_from=valid_from,
            valid_until=valid_until,
        )

    def _private_key_path(self, key_id: str) -> Path:
        return self._directory / f"{key_id}.ed25519-key"

    def _metadata_path(self, key_id: str) -> Path:
        return self._directory / f"{key_id}.json"

    def _write_json_atomic(self, destination: Path, value: dict[str, str]) -> None:
        encoded = json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
        self._write_bytes_atomic(destination, encoded)

    def _write_bytes_atomic(self, destination: Path, value: bytes) -> None:
        self._write_bytes_atomic_to(destination, value)

    @staticmethod
    def _write_bytes_atomic_to(destination: Path, value: bytes) -> None:
        descriptor, temporary_name = tempfile.mkstemp(
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
        )
        temporary_path = Path(temporary_name)
        try:
            if os.name != "nt":
                temporary_path.chmod(0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(value)
                stream.flush()
                os.fsync(stream.fileno())
            temporary_path.replace(destination)
        except BaseException:
            temporary_path.unlink(missing_ok=True)
            raise


def _canonical_uuid(value: str) -> None:
    try:
        parsed = UUID(value)
    except (TypeError, ValueError) as error:
        raise MonitorSigningKeyError("signing key identifier must be a UUID") from error
    if str(parsed) != value:
        raise MonitorSigningKeyError("signing key identifier must use canonical UUID form")


def _aware_datetime(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise MonitorSigningKeyError(f"{label} must include a timezone")
    return value


def _parse_datetime(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise MonitorSigningKeyError(f"{label} is malformed")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise MonitorSigningKeyError(f"{label} is malformed") from error
    return _aware_datetime(parsed, label)
