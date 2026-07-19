"""Versioned data contracts shared across FinRadar trust boundaries."""

from finradar_contracts.regulatory_package import (
    MAX_PACKAGE_BYTES,
    RegulatoryPackageError,
    build_regulatory_package,
    decode_regulatory_package,
    encode_regulatory_package,
    verify_regulatory_package_signature,
)
from finradar_contracts.signatures import (
    RegulatorySignatureError,
    generate_private_key_bytes,
    public_key_bytes,
)
from finradar_contracts.trust_records import (
    TrustRecordError,
    build_public_key_record,
    build_rotation_record,
    decode_rotation_record,
    decode_trust_record,
    encode_rotation_record,
    encode_trust_record,
    verify_rotation_record,
)

__all__ = [
    "MAX_PACKAGE_BYTES",
    "RegulatoryPackageError",
    "RegulatorySignatureError",
    "TrustRecordError",
    "build_regulatory_package",
    "build_public_key_record",
    "build_rotation_record",
    "decode_rotation_record",
    "decode_trust_record",
    "decode_regulatory_package",
    "encode_regulatory_package",
    "encode_rotation_record",
    "encode_trust_record",
    "generate_private_key_bytes",
    "public_key_bytes",
    "verify_regulatory_package_signature",
    "verify_rotation_record",
]
