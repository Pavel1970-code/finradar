import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest

from finradar.infrastructure.regulatory_inbox import (
    RegulatoryInboxError,
    parse_untrusted_regulatory_package_file,
)
from finradar_contracts import (
    MAX_PACKAGE_BYTES,
    RegulatoryPackageError,
    build_regulatory_package,
    decode_regulatory_package,
    encode_regulatory_package,
    generate_private_key_bytes,
    public_key_bytes,
    verify_regulatory_package_signature,
)
from finradar_monitor.package_export import export_regulatory_package
from finradar_monitor.paths import DATA_DIRECTORY_ENV, OUTBOX_DIRECTORY_ENV, MonitorPaths
from finradar_monitor.source_policy import SourcePolicyError, validate_official_source_url
from finradar_monitor.signing_keys import MonitorSigningKey
from finradar_monitor.storage import PublicDocument, RegulatoryStorage


SOURCE_ID = "3b35148e-48af-4b08-9654-b13719f7d867"
CANDIDATE_ID = "c02f613a-9fa1-4d95-88b7-a2d1248ab7d4"
SIGNING_KEY_ID = "ba57de14-7fa4-4a66-8d1e-72297ca18236"
SIGNING_PRIVATE_KEY = generate_private_key_bytes()
SIGNING_PUBLIC_KEY = public_key_bytes(SIGNING_PRIVATE_KEY)


def valid_source() -> dict[str, object]:
    return {
        "source_id": SOURCE_ID,
        "source_url": "https://matsne.gov.ge/ka/document/view/1043717",
        "document_id": "tax-code-1043717",
        "title": "Tax Code of Georgia",
        "publisher": "Legislative Herald of Georgia",
        "publication_date": "2010-10-12",
        "effective_date": "2011-01-01",
        "language": "ka",
        "content_sha256": hashlib.sha256(b"public document").hexdigest(),
    }


def valid_candidate() -> dict[str, object]:
    return {
        "candidate_id": CANDIDATE_ID,
        "rule_type": "late_payment_penalty",
        "source_id": SOURCE_ID,
        "extracted_at": "2026-07-19T09:00:00+04:00",
        "extraction_method": "ai_assisted",
        "confidence": 85,
        "evidence_excerpt": "Public legal evidence excerpt.",
        "rule_data": {
            "daily_rate": "0.0005",
            "valid_from": "2026-01-01",
            "jurisdiction": "GE",
        },
    }


def valid_package() -> dict[str, object]:
    return build_regulatory_package(
        sources=[valid_source()],
        candidates=[valid_candidate()],
        signing_key_id=SIGNING_KEY_ID,
        signing_private_key=SIGNING_PRIVATE_KEY,
        package_id="6692c33a-91c8-436d-850d-38a59b16d672",
        created_at=datetime(2026, 7, 19, 9, 15, tzinfo=timezone.utc),
    )


def test_regulatory_package_round_trip() -> None:
    package = valid_package()
    decoded = decode_regulatory_package(encode_regulatory_package(package))

    assert decoded == package
    assert decoded["payload"]["candidates"][0]["confidence"] == 85
    assert verify_regulatory_package_signature(decoded, SIGNING_PUBLIC_KEY) == decoded


def test_regulatory_package_rejects_tampering() -> None:
    package = valid_package()
    package["payload"]["candidates"][0]["rule_data"]["daily_rate"] = "999"

    with pytest.raises(RegulatoryPackageError, match="checksum"):
        decode_regulatory_package(json.dumps(package))


def test_regulatory_package_rejects_unknown_and_financial_fields() -> None:
    package = valid_package()
    package["unexpected"] = "value"
    with pytest.raises(RegulatoryPackageError, match="unexpected"):
        decode_regulatory_package(json.dumps(package))

    candidate = valid_candidate()
    candidate["rule_data"]["company_id"] = 12
    with pytest.raises(RegulatoryPackageError, match="forbidden financial field"):
        build_regulatory_package(
            sources=[valid_source()],
            candidates=[candidate],
            signing_key_id=SIGNING_KEY_ID,
            signing_private_key=SIGNING_PRIVATE_KEY,
        )

    candidate = valid_candidate()
    candidate["rule_data"]["private_key"] = "must-never-cross"
    with pytest.raises(RegulatoryPackageError, match="forbidden secret field"):
        build_regulatory_package(
            sources=[valid_source()],
            candidates=[candidate],
            signing_key_id=SIGNING_KEY_ID,
            signing_private_key=SIGNING_PRIVATE_KEY,
        )


def test_regulatory_package_rejects_invalid_signature() -> None:
    package = valid_package()
    package["created_at"] = "2026-07-19T09:16:00+00:00"

    with pytest.raises(RegulatoryPackageError, match="signature verification"):
        verify_regulatory_package_signature(package, SIGNING_PUBLIC_KEY)


def test_regulatory_package_limits_signature_and_lifetime() -> None:
    package = valid_package()
    package["signature"]["value"] = "invalid"
    with pytest.raises(RegulatoryPackageError, match="canonical base64"):
        decode_regulatory_package(json.dumps(package))

    with pytest.raises(RegulatoryPackageError, match="seven days"):
        build_regulatory_package(
            sources=[valid_source()],
            candidates=[valid_candidate()],
            signing_key_id=SIGNING_KEY_ID,
            signing_private_key=SIGNING_PRIVATE_KEY,
            created_at=datetime(2026, 7, 19, tzinfo=timezone.utc),
            expires_at=datetime(2026, 7, 27, tzinfo=timezone.utc),
        )


def test_regulatory_package_rejects_unsafe_json() -> None:
    with pytest.raises(RegulatoryPackageError, match="duplicate JSON key"):
        decode_regulatory_package('{"schema_version":1,"schema_version":1}')

    with pytest.raises(RegulatoryPackageError, match="maximum allowed size"):
        decode_regulatory_package(b"x" * (MAX_PACKAGE_BYTES + 1))


@pytest.mark.parametrize(
    "url",
    [
        "http://matsne.gov.ge/document",
        "https://matsne.gov.ge.evil.example/document",
        "https://matsne.gov.ge@evil.example/document",
        "https://matsne.gov.ge:444/document",
        "https://example.com/document",
    ],
)
def test_source_policy_rejects_non_official_urls(url: str) -> None:
    with pytest.raises(SourcePolicyError):
        validate_official_source_url(url)


def test_source_policy_accepts_official_https_url() -> None:
    url = "https://services.nbg.gov.ge/Rates/Service.asmx"
    assert validate_official_source_url(url) == url


def test_monitor_has_separate_storage_location(tmp_path: Path, monkeypatch) -> None:
    monitor_directory = tmp_path / "monitor-only"
    monkeypatch.setenv(DATA_DIRECTORY_ENV, str(monitor_directory))
    paths = MonitorPaths.from_environment()
    paths.create()
    storage = RegulatoryStorage(paths.database_path)
    storage.initialize()
    source_id = storage.record_document(
        PublicDocument(
            source_url="https://rs.ge/LegalEntityPreferentialTax-en",
            document_id="rs-preferential-tax",
            title="Preferential taxation",
            publisher="Revenue Service Georgia",
            language="en",
            content="Public information only.",
            fetched_at=datetime(2026, 7, 19, 9, 0, tzinfo=timezone.utc),
        )
    )

    assert UUID(source_id)
    assert paths.database_path == monitor_directory / "regulatory_monitor.db"
    assert paths.signing_key_directory == monitor_directory / "signing-keys"
    assert storage.count_documents() == 1
    assert not (monitor_directory / "finradar.db").exists()
    with sqlite3.connect(paths.database_path) as connection:
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(public_documents)").fetchall()
        }
    assert "company_id" not in columns
    assert "account_number" not in columns


def test_monitor_outbox_can_be_an_acl_separated_exchange(tmp_path: Path, monkeypatch) -> None:
    monitor_directory = tmp_path / "monitor-private"
    exchange_directory = tmp_path / "one-way-exchange"
    monkeypatch.setenv(DATA_DIRECTORY_ENV, str(monitor_directory))
    monkeypatch.setenv(OUTBOX_DIRECTORY_ENV, str(exchange_directory))

    paths = MonitorPaths.from_environment()
    paths.create()

    assert paths.database_path.parent == monitor_directory
    assert paths.outbox_directory == exchange_directory
    assert exchange_directory.is_dir()


def test_monitor_export_is_accepted_by_core_inbox(tmp_path: Path) -> None:
    signing_key = MonitorSigningKey(
        key_id=SIGNING_KEY_ID,
        private_key=SIGNING_PRIVATE_KEY,
        public_key=SIGNING_PUBLIC_KEY,
        valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        valid_until=datetime(2027, 1, 1, tzinfo=timezone.utc),
    )
    package_path = export_regulatory_package(
        outbox_directory=tmp_path,
        sources=[valid_source()],
        candidates=[valid_candidate()],
        signing_key=signing_key,
    )

    imported = parse_untrusted_regulatory_package_file(package_path)

    assert imported["producer"] == "finradar-regulatory-monitor"
    assert imported["payload"]["sources"][0]["source_id"] == SOURCE_ID
    assert imported["signature"]["key_id"] == SIGNING_KEY_ID


def test_core_inbox_rejects_non_json_extension(tmp_path: Path) -> None:
    package_path = tmp_path / "regulatory.zip"
    package_path.write_bytes(encode_regulatory_package(valid_package()))

    with pytest.raises(RegulatoryInboxError, match="JSON"):
        parse_untrusted_regulatory_package_file(package_path)
