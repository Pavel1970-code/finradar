"""Strict public-key bootstrap and signed rotation records."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from finradar_contracts.signatures import (
    SIGNATURE_ALGORITHM,
    RegulatorySignatureError,
    decode_base64,
    encode_base64,
    signature_value_for_domain,
    verify_signature_for_domain,
)


TRUST_RECORD_SCHEMA = 1
ROTATION_RECORD_SCHEMA = 1
ROTATION_DOMAIN = b"FinRadar regulatory key rotation v1\x00"
MAX_TRUST_RECORD_BYTES = 8 * 1024
MAX_ROTATION_RECORD_BYTES = 16 * 1024
MAX_ROTATION_LIFETIME = timedelta(hours=24)
MAX_KEY_LIFETIME = timedelta(days=366)
PUBLIC_KEY_FIELDS = {
    "schema_version",
    "algorithm",
    "key_id",
    "public_key_base64",
    "public_key_fingerprint",
    "valid_from",
    "valid_until",
}
ROTATION_FIELDS = {
    "schema_version",
    "rotation_id",
    "issued_at",
    "expires_at",
    "previous_key_id",
    "new_key",
    "signature",
}
ROTATION_SIGNATURE_FIELDS = {"algorithm", "key_id", "value"}


class TrustRecordError(ValueError):
    pass


def build_public_key_record(
    *,
    key_id: str,
    public_key: bytes,
    valid_from: datetime,
    valid_until: datetime,
) -> dict[str, Any]:
    record = {
        "schema_version": TRUST_RECORD_SCHEMA,
        "algorithm": SIGNATURE_ALGORITHM,
        "key_id": key_id,
        "public_key_base64": encode_base64(public_key),
        "public_key_fingerprint": hashlib.sha256(public_key).hexdigest(),
        "valid_from": valid_from.isoformat(),
        "valid_until": valid_until.isoformat(),
    }
    return validate_public_key_record(record)


def validate_public_key_record(record: object) -> dict[str, Any]:
    value = _exact_object(record, PUBLIC_KEY_FIELDS, "public key record")
    if type(value["schema_version"]) is not int or value["schema_version"] != TRUST_RECORD_SCHEMA:
        raise TrustRecordError("unsupported public key record schema")
    if value["algorithm"] != SIGNATURE_ALGORITHM:
        raise TrustRecordError("unsupported public key algorithm")
    _uuid(value["key_id"], "key_id")
    try:
        public_key = decode_base64(
            value["public_key_base64"], expected_bytes=32, label="public key"
        )
    except RegulatorySignatureError as error:
        raise TrustRecordError(str(error)) from error
    if hashlib.sha256(public_key).hexdigest() != value["public_key_fingerprint"]:
        raise TrustRecordError("public key fingerprint does not match")
    valid_from = _datetime(value["valid_from"], "valid_from")
    valid_until = _datetime(value["valid_until"], "valid_until")
    if valid_until <= valid_from or valid_until - valid_from > MAX_KEY_LIFETIME:
        raise TrustRecordError("public key lifetime is invalid")
    return json.loads(_canonical(value))


def encode_trust_record(record: object) -> bytes:
    validated = validate_public_key_record(record)
    encoded = _canonical(validated).encode("utf-8")
    if len(encoded) > MAX_TRUST_RECORD_BYTES:
        raise TrustRecordError("public key record is too large")
    return encoded


def decode_trust_record(raw: bytes) -> dict[str, Any]:
    if len(raw) > MAX_TRUST_RECORD_BYTES:
        raise TrustRecordError("public key record is too large")
    return validate_public_key_record(_decode(raw, "public key record"))


def build_rotation_record(
    *,
    previous_key_id: str,
    previous_private_key: bytes,
    new_key: dict[str, Any],
    issued_at: datetime | None = None,
    expires_at: datetime | None = None,
    rotation_id: str | None = None,
) -> dict[str, Any]:
    issued = issued_at or datetime.now(timezone.utc)
    expires = expires_at or issued + timedelta(hours=6)
    record = {
        "schema_version": ROTATION_RECORD_SCHEMA,
        "rotation_id": rotation_id or str(uuid4()),
        "issued_at": issued.isoformat(),
        "expires_at": expires.isoformat(),
        "previous_key_id": previous_key_id,
        "new_key": validate_public_key_record(new_key),
        "signature": {
            "algorithm": SIGNATURE_ALGORITHM,
            "key_id": previous_key_id,
            "value": "",
        },
    }
    record["signature"]["value"] = signature_value_for_domain(
        record, previous_private_key, ROTATION_DOMAIN
    )
    return validate_rotation_record(record)


def validate_rotation_record(record: object) -> dict[str, Any]:
    value = _exact_object(record, ROTATION_FIELDS, "rotation record")
    if (
        type(value["schema_version"]) is not int
        or value["schema_version"] != ROTATION_RECORD_SCHEMA
    ):
        raise TrustRecordError("unsupported rotation record schema")
    _uuid(value["rotation_id"], "rotation_id")
    _uuid(value["previous_key_id"], "previous_key_id")
    issued = _datetime(value["issued_at"], "issued_at")
    expires = _datetime(value["expires_at"], "expires_at")
    if expires <= issued or expires - issued > MAX_ROTATION_LIFETIME:
        raise TrustRecordError("rotation record lifetime is invalid")
    value["new_key"] = validate_public_key_record(value["new_key"])
    signature = _exact_object(
        value["signature"], ROTATION_SIGNATURE_FIELDS, "rotation signature"
    )
    if signature["algorithm"] != SIGNATURE_ALGORITHM:
        raise TrustRecordError("unsupported rotation signature algorithm")
    if signature["key_id"] != value["previous_key_id"]:
        raise TrustRecordError("rotation signer does not match previous key")
    try:
        decode_base64(signature["value"], expected_bytes=64, label="rotation signature")
    except RegulatorySignatureError as error:
        raise TrustRecordError(str(error)) from error
    return json.loads(_canonical(value))


def verify_rotation_record(record: object, previous_public_key: bytes) -> dict[str, Any]:
    validated = validate_rotation_record(record)
    try:
        verify_signature_for_domain(validated, previous_public_key, ROTATION_DOMAIN)
    except RegulatorySignatureError as error:
        raise TrustRecordError("rotation signature verification failed") from error
    return validated


def encode_rotation_record(record: object) -> bytes:
    encoded = _canonical(validate_rotation_record(record)).encode("utf-8")
    if len(encoded) > MAX_ROTATION_RECORD_BYTES:
        raise TrustRecordError("rotation record is too large")
    return encoded


def decode_rotation_record(raw: bytes) -> dict[str, Any]:
    if len(raw) > MAX_ROTATION_RECORD_BYTES:
        raise TrustRecordError("rotation record is too large")
    return validate_rotation_record(_decode(raw, "rotation record"))


def _decode(raw: bytes, label: str) -> object:
    try:
        return json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise TrustRecordError(f"{label} is not valid UTF-8 JSON") from error


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise TrustRecordError(f"duplicate JSON field: {key}")
        value[key] = item
    return value


def _exact_object(value: object, fields: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise TrustRecordError(f"{label} has invalid fields")
    return dict(value)


def _uuid(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise TrustRecordError(f"{label} must be a UUID")
    try:
        parsed = UUID(value)
    except ValueError as error:
        raise TrustRecordError(f"{label} must be a UUID") from error
    if str(parsed) != value:
        raise TrustRecordError(f"{label} must use canonical UUID form")
    return value


def _datetime(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise TrustRecordError(f"{label} must be an ISO datetime")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise TrustRecordError(f"{label} must be an ISO datetime") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise TrustRecordError(f"{label} must include a timezone")
    return parsed


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
