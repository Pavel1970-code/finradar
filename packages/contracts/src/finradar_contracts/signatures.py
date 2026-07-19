"""Ed25519 primitives for signed regulatory packages."""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Mapping
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


SIGNATURE_ALGORITHM = "Ed25519"
SIGNATURE_DOMAIN = b"FinRadar regulatory package v2\x00"
PRIVATE_KEY_BYTES = 32
PUBLIC_KEY_BYTES = 32
SIGNATURE_BYTES = 64


class RegulatorySignatureError(ValueError):
    """A key or package signature is malformed or invalid."""


def generate_private_key_bytes() -> bytes:
    return Ed25519PrivateKey.generate().private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )


def public_key_bytes(private_key_bytes: bytes) -> bytes:
    private_key = _load_private_key(private_key_bytes)
    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def signature_value(document: Mapping[str, Any], private_key_bytes: bytes) -> str:
    private_key = _load_private_key(private_key_bytes)
    signature = private_key.sign(_signature_input(document))
    return base64.b64encode(signature).decode("ascii")


def verify_signature(document: Mapping[str, Any], public_key: bytes) -> None:
    signature_object = document.get("signature")
    if not isinstance(signature_object, Mapping):
        raise RegulatorySignatureError("package signature is missing")
    encoded_signature = signature_object.get("value")
    if not isinstance(encoded_signature, str):
        raise RegulatorySignatureError("package signature value is malformed")
    signature = decode_base64(
        encoded_signature,
        expected_bytes=SIGNATURE_BYTES,
        label="package signature",
    )
    if len(public_key) != PUBLIC_KEY_BYTES:
        raise RegulatorySignatureError("Ed25519 public key must be 32 bytes")
    try:
        verifier = Ed25519PublicKey.from_public_bytes(public_key)
        verifier.verify(signature, _signature_input(document))
    except (InvalidSignature, ValueError) as error:
        raise RegulatorySignatureError("package signature verification failed") from error


def encode_base64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def decode_base64(value: str, *, expected_bytes: int, label: str) -> bytes:
    if not isinstance(value, str):
        raise RegulatorySignatureError(f"{label} must be canonical base64")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as error:
        raise RegulatorySignatureError(f"{label} must be canonical base64") from error
    if len(decoded) != expected_bytes or encode_base64(decoded) != value:
        raise RegulatorySignatureError(
            f"{label} must encode exactly {expected_bytes} bytes"
        )
    return decoded


def _load_private_key(private_key_bytes: bytes) -> Ed25519PrivateKey:
    if len(private_key_bytes) != PRIVATE_KEY_BYTES:
        raise RegulatorySignatureError("Ed25519 private key must be 32 bytes")
    try:
        return Ed25519PrivateKey.from_private_bytes(private_key_bytes)
    except ValueError as error:
        raise RegulatorySignatureError("Ed25519 private key is invalid") from error


def _signature_input(document: Mapping[str, Any]) -> bytes:
    signable = dict(document)
    signature_object = signable.get("signature")
    if not isinstance(signature_object, Mapping):
        raise RegulatorySignatureError("package signature is missing")
    signable["signature"] = {
        "algorithm": signature_object.get("algorithm"),
        "key_id": signature_object.get("key_id"),
        "value": "",
    }
    canonical = json.dumps(
        signable,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return SIGNATURE_DOMAIN + canonical
