"""Strict, public-only contract for one-way Monitor-to-Core exchange."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from finradar_contracts.source_policy import SourcePolicyError, validate_official_source_url


SCHEMA_VERSION = 1
PRODUCER = "finradar-regulatory-monitor"
MAX_PACKAGE_BYTES = 5 * 1024 * 1024
MAX_SOURCES = 100
MAX_CANDIDATES = 1_000
MAX_EVIDENCE_CHARACTERS = 20_000

PACKAGE_KEYS = {
    "schema_version",
    "package_id",
    "created_at",
    "producer",
    "payload",
    "payload_sha256",
}
PAYLOAD_KEYS = {"sources", "candidates"}
SOURCE_KEYS = {
    "source_id",
    "source_url",
    "document_id",
    "title",
    "publisher",
    "publication_date",
    "effective_date",
    "language",
    "content_sha256",
}
CANDIDATE_KEYS = {
    "candidate_id",
    "rule_type",
    "source_id",
    "extracted_at",
    "extraction_method",
    "confidence",
    "evidence_excerpt",
    "rule_data",
}
RULE_TYPES = {
    "exchange_rate",
    "fine",
    "late_payment_penalty",
    "payment_deadline",
    "tax_benefit",
    "tax_obligation",
    "tax_refund",
}
EXTRACTION_METHODS = {"ai_assisted", "manual", "structured_source"}
FORBIDDEN_FINANCIAL_KEYS = {
    "account_number",
    "analysis_run_id",
    "bank_account",
    "cash_accounts",
    "cash_balance",
    "cash_flow_items",
    "company_id",
    "company_name",
    "customer_data",
    "financial_snapshot",
    "synchronization_run_id",
    "taxpayer_id",
    "transaction_id",
    "transactions",
}


class RegulatoryPackageError(ValueError):
    """The package is malformed, unsafe, or fails integrity checks."""


def build_regulatory_package(
    *,
    sources: Iterable[Mapping[str, Any]],
    candidates: Iterable[Mapping[str, Any]],
    package_id: str | None = None,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    timestamp = created_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise RegulatoryPackageError("created_at must include a timezone")

    payload = {
        "sources": [dict(item) for item in sources],
        "candidates": [dict(item) for item in candidates],
    }
    package = {
        "schema_version": SCHEMA_VERSION,
        "package_id": package_id or str(uuid4()),
        "created_at": timestamp.isoformat(),
        "producer": PRODUCER,
        "payload": payload,
        "payload_sha256": _payload_checksum(payload),
    }
    return validate_regulatory_package(package)


def encode_regulatory_package(package: Mapping[str, Any]) -> bytes:
    validated = validate_regulatory_package(package)
    encoded = _canonical_json(validated)
    if len(encoded) > MAX_PACKAGE_BYTES:
        raise RegulatoryPackageError("package exceeds the maximum allowed size")
    return encoded


def decode_regulatory_package(raw_package: bytes | str) -> dict[str, Any]:
    raw_bytes = (
        raw_package.encode("utf-8")
        if isinstance(raw_package, str)
        else raw_package
    )
    if len(raw_bytes) > MAX_PACKAGE_BYTES:
        raise RegulatoryPackageError("package exceeds the maximum allowed size")

    try:
        document = json.loads(raw_bytes, object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RegulatoryPackageError("package is not valid UTF-8 JSON") from error

    if not isinstance(document, dict):
        raise RegulatoryPackageError("package root must be a JSON object")
    return validate_regulatory_package(document)


def validate_regulatory_package(package: Mapping[str, Any]) -> dict[str, Any]:
    document = _require_object(package, "package")
    _require_exact_keys(document, PACKAGE_KEYS, "package")

    if document["schema_version"] != SCHEMA_VERSION:
        raise RegulatoryPackageError("unsupported regulatory package schema version")
    _require_uuid(document["package_id"], "package.package_id")
    _require_datetime(document["created_at"], "package.created_at")
    if document["producer"] != PRODUCER:
        raise RegulatoryPackageError("unexpected package producer")

    payload = _require_object(document["payload"], "package.payload")
    _require_exact_keys(payload, PAYLOAD_KEYS, "package.payload")
    sources = _require_list(payload["sources"], "package.payload.sources", MAX_SOURCES)
    candidates = _require_list(
        payload["candidates"],
        "package.payload.candidates",
        MAX_CANDIDATES,
    )

    source_ids: set[str] = set()
    for index, source in enumerate(sources):
        path = f"package.payload.sources[{index}]"
        source_object = _require_object(source, path)
        _require_exact_keys(source_object, SOURCE_KEYS, path)
        source_id = _require_uuid(source_object["source_id"], f"{path}.source_id")
        if source_id in source_ids:
            raise RegulatoryPackageError("source_id values must be unique")
        source_ids.add(source_id)
        source_url = _require_text(source_object["source_url"], f"{path}.source_url", 2_048)
        try:
            validate_official_source_url(source_url)
        except SourcePolicyError as error:
            raise RegulatoryPackageError(f"{path}.source_url: {error}") from error
        _require_text(source_object["document_id"], f"{path}.document_id", 500)
        _require_text(source_object["title"], f"{path}.title", 1_000)
        _require_text(source_object["publisher"], f"{path}.publisher", 500)
        _require_optional_date(source_object["publication_date"], f"{path}.publication_date")
        _require_optional_date(source_object["effective_date"], f"{path}.effective_date")
        _require_text(source_object["language"], f"{path}.language", 20)
        _require_sha256(source_object["content_sha256"], f"{path}.content_sha256")

    candidate_ids: set[str] = set()
    for index, candidate in enumerate(candidates):
        path = f"package.payload.candidates[{index}]"
        candidate_object = _require_object(candidate, path)
        _require_exact_keys(candidate_object, CANDIDATE_KEYS, path)
        candidate_id = _require_uuid(candidate_object["candidate_id"], f"{path}.candidate_id")
        if candidate_id in candidate_ids:
            raise RegulatoryPackageError("candidate_id values must be unique")
        candidate_ids.add(candidate_id)
        if candidate_object["rule_type"] not in RULE_TYPES:
            raise RegulatoryPackageError(f"{path}.rule_type is not supported")
        source_id = _require_uuid(candidate_object["source_id"], f"{path}.source_id")
        if source_id not in source_ids:
            raise RegulatoryPackageError(f"{path}.source_id has no matching source")
        _require_datetime(candidate_object["extracted_at"], f"{path}.extracted_at")
        if candidate_object["extraction_method"] not in EXTRACTION_METHODS:
            raise RegulatoryPackageError(f"{path}.extraction_method is not supported")
        confidence = candidate_object["confidence"]
        if type(confidence) is not int or not 0 <= confidence <= 100:
            raise RegulatoryPackageError(f"{path}.confidence must be an integer from 0 to 100")
        _require_text(
            candidate_object["evidence_excerpt"],
            f"{path}.evidence_excerpt",
            MAX_EVIDENCE_CHARACTERS,
        )
        rule_data = _require_object(candidate_object["rule_data"], f"{path}.rule_data")
        _validate_public_json(rule_data, f"{path}.rule_data")

    _reject_financial_keys(document)
    _require_sha256(document["payload_sha256"], "package.payload_sha256")
    expected_checksum = _payload_checksum(payload)
    if document["payload_sha256"] != expected_checksum:
        raise RegulatoryPackageError("payload checksum does not match package contents")

    return json.loads(_canonical_json(document))


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _payload_checksum(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RegulatoryPackageError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _require_object(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise RegulatoryPackageError(f"{path} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise RegulatoryPackageError(f"{path} keys must be strings")
    return dict(value)


def _require_list(value: Any, path: str, limit: int) -> list[Any]:
    if not isinstance(value, list):
        raise RegulatoryPackageError(f"{path} must be an array")
    if len(value) > limit:
        raise RegulatoryPackageError(f"{path} contains too many items")
    return value


def _require_exact_keys(value: Mapping[str, Any], expected: set[str], path: str) -> None:
    actual = set(value)
    if actual == expected:
        return
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    details: list[str] = []
    if missing:
        details.append(f"missing: {', '.join(missing)}")
    if unexpected:
        details.append(f"unexpected: {', '.join(unexpected)}")
    raise RegulatoryPackageError(f"{path} has invalid fields ({'; '.join(details)})")


def _require_text(value: Any, path: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RegulatoryPackageError(f"{path} must be non-empty text")
    if len(value) > maximum:
        raise RegulatoryPackageError(f"{path} is too long")
    return value


def _require_uuid(value: Any, path: str) -> str:
    text = _require_text(value, path, 36)
    try:
        parsed = UUID(text)
    except ValueError as error:
        raise RegulatoryPackageError(f"{path} must be a UUID") from error
    if str(parsed) != text:
        raise RegulatoryPackageError(f"{path} must use canonical UUID form")
    return text


def _require_datetime(value: Any, path: str) -> datetime:
    text = _require_text(value, path, 50)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise RegulatoryPackageError(f"{path} must be an ISO 8601 datetime") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RegulatoryPackageError(f"{path} must include a timezone")
    return parsed


def _require_optional_date(value: Any, path: str) -> date | None:
    if value is None:
        return None
    text = _require_text(value, path, 10)
    try:
        parsed = date.fromisoformat(text)
    except ValueError as error:
        raise RegulatoryPackageError(f"{path} must be an ISO 8601 date or null") from error
    if parsed.isoformat() != text:
        raise RegulatoryPackageError(f"{path} must use YYYY-MM-DD form")
    return parsed


def _require_sha256(value: Any, path: str) -> str:
    text = _require_text(value, path, 64)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise RegulatoryPackageError(f"{path} must be a lowercase SHA-256 digest")
    return text


def _validate_public_json(value: Any, path: str, depth: int = 0) -> None:
    if depth > 20:
        raise RegulatoryPackageError(f"{path} is nested too deeply")
    if value is None or isinstance(value, (str, bool)):
        return
    if type(value) is int:
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise RegulatoryPackageError(f"{path} contains a non-finite number")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_public_json(item, f"{path}[{index}]", depth + 1)
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise RegulatoryPackageError(f"{path} keys must be strings")
            _validate_public_json(item, f"{path}.{key}", depth + 1)
        return
    raise RegulatoryPackageError(f"{path} contains a non-JSON value")


def _reject_financial_keys(value: Any, path: str = "package") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key.casefold() in FORBIDDEN_FINANCIAL_KEYS:
                raise RegulatoryPackageError(f"{path}.{key} is a forbidden financial field")
            _reject_financial_keys(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_financial_keys(item, f"{path}[{index}]")
