import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from finradar.infrastructure.database import migrate_database
from finradar.infrastructure.models import (
    RegulatoryAcceptedPackage,
    RegulatoryPackageImport,
)
from finradar.infrastructure.regulatory_inbox import (
    RegulatoryImportOutcome,
    RegulatoryInboxError,
    RegulatoryInboxPaths,
    RegulatoryPackageImporter,
)
from finradar.infrastructure.regulatory_trust_store import (
    RegulatoryTrustError,
    SqlAlchemyRegulatoryTrustStore,
    TrustedKeyStatus,
)
from finradar_contracts import (
    MAX_PACKAGE_BYTES,
    build_regulatory_package,
    encode_regulatory_package,
    generate_private_key_bytes,
    public_key_bytes,
)
from finradar_monitor.signing_keys import (
    MonitorSigningKeyError,
    MonitorSigningKeyStore,
)


NOW = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)
SOURCE_ID = "46be99d2-23ee-4b86-9914-e962627c8421"


def make_session_factory(database_path: Path):
    engine = create_engine(f"sqlite:///{database_path}")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, connection_record) -> None:
        del connection_record
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.close()

    migrate_database(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def source() -> dict[str, object]:
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


def candidate() -> dict[str, object]:
    return {
        "candidate_id": str(uuid4()),
        "rule_type": "payment_deadline",
        "source_id": SOURCE_ID,
        "extracted_at": NOW.isoformat(),
        "extraction_method": "structured_source",
        "confidence": 100,
        "evidence_excerpt": "Public statutory deadline.",
        "rule_data": {"due_day": 15, "jurisdiction": "GE"},
    }


def signed_package(
    *,
    key_id: str,
    private_key: bytes,
    package_id: str | None = None,
    created_at: datetime = NOW,
    expires_at: datetime | None = None,
) -> dict[str, object]:
    return build_regulatory_package(
        sources=[source()],
        candidates=[candidate()],
        signing_key_id=key_id,
        signing_private_key=private_key,
        package_id=package_id,
        created_at=created_at,
        expires_at=expires_at,
    )


def write_package(path: Path, package: dict[str, object]) -> Path:
    path.write_bytes(encode_regulatory_package(package))
    return path


def security_context(tmp_path: Path):
    session_factory = make_session_factory(tmp_path / "security.db")
    trust_store = SqlAlchemyRegulatoryTrustStore(session_factory)
    private_key = generate_private_key_bytes()
    key_id = str(uuid4())
    trust_store.add_trusted_key(
        key_id=key_id,
        public_key=public_key_bytes(private_key),
        valid_from=NOW - timedelta(days=1),
        valid_until=NOW + timedelta(days=180),
        reason="Provisioned with the signed application release.",
    )
    importer = RegulatoryPackageImporter(
        session_factory,
        trust_store=trust_store,
        paths=RegulatoryInboxPaths.under(tmp_path / "archive"),
    )
    return session_factory, trust_store, importer, key_id, private_key


def test_monitor_key_store_creates_activates_and_detects_tampering(tmp_path: Path) -> None:
    store = MonitorSigningKeyStore(tmp_path / "private-keys")
    key = store.create_key(
        valid_from=NOW - timedelta(days=1),
        valid_until=NOW + timedelta(days=180),
    )
    store.activate_key(key.key_id, at_time=NOW)

    loaded = store.load_active(at_time=NOW)

    assert loaded == key
    assert key.public_key_fingerprint == hashlib.sha256(key.public_key).hexdigest()
    assert key.private_key not in (tmp_path / "private-keys" / f"{key.key_id}.json").read_bytes()
    assert (tmp_path / "private-keys" / f"{key.key_id}.ed25519-key").stat().st_mode & 0o077 == 0

    (tmp_path / "private-keys" / f"{key.key_id}.ed25519-key").write_bytes(b"x" * 32)
    with pytest.raises(MonitorSigningKeyError, match="integrity"):
        store.load_key(key.key_id)


def test_trust_store_supports_overlap_and_irreversible_revocation(tmp_path: Path) -> None:
    session_factory = make_session_factory(tmp_path / "trust.db")
    store = SqlAlchemyRegulatoryTrustStore(session_factory)
    first_private = generate_private_key_bytes()
    second_private = generate_private_key_bytes()
    first_id = str(uuid4())
    second_id = str(uuid4())

    for key_id, private_key in ((first_id, first_private), (second_id, second_private)):
        store.add_trusted_key(
            key_id=key_id,
            public_key=public_key_bytes(private_key),
            valid_from=NOW - timedelta(days=1),
            valid_until=NOW + timedelta(days=90),
            reason="Overlapping key rotation window.",
        )

    assert store.verification_key(first_id, signed_at=NOW) == public_key_bytes(first_private)
    assert store.verification_key(second_id, signed_at=NOW) == public_key_bytes(second_private)

    store.revoke_key(first_id, reason="Rotation completed; old key revoked.")

    assert store.lifecycle(first_id) == (
        TrustedKeyStatus.TRUSTED,
        TrustedKeyStatus.REVOKED,
    )
    with pytest.raises(RegulatoryTrustError) as error:
        store.verification_key(first_id, signed_at=NOW)
    assert error.value.code == "revoked_key"
    with pytest.raises(ValueError, match="already revoked"):
        store.revoke_key(first_id, reason="Cannot revoke twice.")


def test_verified_package_is_accepted_archived_and_audited(tmp_path: Path) -> None:
    session_factory, _, importer, key_id, private_key = security_context(tmp_path)
    package_id = str(uuid4())
    package_path = write_package(
        tmp_path / "package.finradar-regulatory.json",
        signed_package(key_id=key_id, private_key=private_key, package_id=package_id),
    )

    result = importer.import_file(package_path, received_at=NOW + timedelta(minutes=1))

    assert result.outcome is RegulatoryImportOutcome.ACCEPTED
    assert result.package_id == package_id
    assert result.package is not None
    assert result.archive_path.parent.name == "accepted"
    assert result.archive_path.read_bytes() == package_path.read_bytes()
    assert importer.load_archived_bytes(result.import_id) == package_path.read_bytes()
    with session_factory() as session:
        audit = session.get(RegulatoryPackageImport, result.import_id)
        accepted = session.get(RegulatoryAcceptedPackage, package_id)
        assert audit is not None and audit.reason_code == "verified"
        assert accepted is not None and accepted.import_id == result.import_id

    result.archive_path.chmod(0o600)
    result.archive_path.write_bytes(b"tampered archive")
    with pytest.raises(RegulatoryInboxError, match="integrity check failed"):
        importer.load_archived_bytes(result.import_id)


def test_replay_is_quarantined_and_every_attempt_is_audited(tmp_path: Path) -> None:
    session_factory, _, importer, key_id, private_key = security_context(tmp_path)
    package_id = str(uuid4())
    package_path = write_package(
        tmp_path / "replay.json",
        signed_package(key_id=key_id, private_key=private_key, package_id=package_id),
    )

    first = importer.import_file(package_path, received_at=NOW + timedelta(minutes=1))
    replay = importer.import_file(package_path, received_at=NOW + timedelta(minutes=2))

    assert first.outcome is RegulatoryImportOutcome.ACCEPTED
    assert replay.outcome is RegulatoryImportOutcome.REPLAYED
    assert replay.reason_code == "replayed_package"
    assert replay.archive_path.parent.name == "quarantine"
    with session_factory() as session:
        attempts = session.scalar(
            select(func.count()).select_from(RegulatoryPackageImport)
        )
        accepted = session.scalar(
            select(func.count()).select_from(RegulatoryAcceptedPackage)
        )
    assert attempts == 2
    assert accepted == 1


@pytest.mark.parametrize(
    ("scenario", "expected_code"),
    [
        ("untrusted", "untrusted_key"),
        ("revoked", "revoked_key"),
        ("expired", "expired_package"),
        ("future", "future_package"),
        ("invalid_signature", "invalid_signature"),
    ],
)
def test_untrusted_or_invalid_packages_are_quarantined(
    tmp_path: Path,
    scenario: str,
    expected_code: str,
) -> None:
    session_factory, trust_store, importer, key_id, private_key = security_context(tmp_path)
    created_at = NOW
    expires_at = None
    if scenario == "untrusted":
        key_id = str(uuid4())
        private_key = generate_private_key_bytes()
    elif scenario == "revoked":
        trust_store.revoke_key(key_id, reason="Compromised key.")
    elif scenario == "expired":
        created_at = NOW - timedelta(days=3)
        expires_at = created_at + timedelta(hours=24)
    elif scenario == "future":
        created_at = NOW + timedelta(hours=1)

    package = signed_package(
        key_id=key_id,
        private_key=private_key,
        created_at=created_at,
        expires_at=expires_at,
    )
    if scenario == "invalid_signature":
        package["created_at"] = (NOW - timedelta(minutes=1)).isoformat()
    package_path = write_package(tmp_path / f"{scenario}.json", package)

    result = importer.import_file(package_path, received_at=NOW)

    assert result.outcome is RegulatoryImportOutcome.QUARANTINED
    assert result.reason_code == expected_code
    assert result.archive_path.parent.name == "quarantine"
    with session_factory() as session:
        assert session.get(RegulatoryAcceptedPackage, result.package_id) is None
        assert session.get(RegulatoryPackageImport, result.import_id) is not None


def test_import_audit_and_replay_records_are_immutable(tmp_path: Path) -> None:
    session_factory, _, importer, key_id, private_key = security_context(tmp_path)
    package_path = write_package(
        tmp_path / "immutable.json",
        signed_package(key_id=key_id, private_key=private_key),
    )
    result = importer.import_file(package_path, received_at=NOW)

    with session_factory() as session:
        with pytest.raises(IntegrityError, match="immutable"):
            session.execute(
                text(
                    "UPDATE regulatory_package_imports "
                    "SET reason_code = 'changed' WHERE id = :id"
                ),
                {"id": result.import_id},
            )
            session.commit()

    with session_factory() as session:
        with pytest.raises(IntegrityError, match="immutable"):
            session.execute(
                text(
                    "DELETE FROM regulatory_accepted_packages WHERE package_id = :package_id"
                ),
                {"package_id": result.package_id},
            )
            session.commit()


def test_malformed_oversized_and_symlink_attempts_are_audited(tmp_path: Path) -> None:
    session_factory, _, importer, _, _ = security_context(tmp_path)
    malformed_path = tmp_path / "malformed.json"
    malformed_path.write_text("{broken", encoding="utf-8")
    oversized_path = tmp_path / "oversized.json"
    oversized_path.write_bytes(b"x" * (MAX_PACKAGE_BYTES + 1))
    target_path = tmp_path / "target.json"
    target_path.write_text("{}", encoding="utf-8")
    symlink_path = tmp_path / "linked.json"
    symlink_path.symlink_to(target_path)

    malformed = importer.import_file(malformed_path, received_at=NOW)
    oversized = importer.import_file(oversized_path, received_at=NOW)
    symlinked = importer.import_file(symlink_path, received_at=NOW)

    assert malformed.reason_code == "malformed_package"
    assert malformed.archive_path is not None
    assert oversized.reason_code == "oversized_package"
    assert oversized.archive_path is None
    assert symlinked.reason_code == "symbolic_link"
    assert symlinked.archive_path is None
    with session_factory() as session:
        audits = tuple(session.scalars(select(RegulatoryPackageImport)))
    assert len(audits) == 3
    assert sum(item.content_hash is None for item in audits) == 2
