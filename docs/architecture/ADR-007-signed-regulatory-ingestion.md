# ADR-007: Signed regulatory package ingestion

- Status: Accepted
- Date: 2026-07-19
- Product: FinRadar

## Context

A SHA-256 checksum detects accidental corruption but does not authenticate the
producer. A local attacker able to replace an exchange file could recalculate a
checksum. Core therefore needs package authenticity, expiry, replay protection,
quarantine, and an immutable record of every import decision before Monitor
network access is enabled.

The signing design must preserve the trust boundary: Monitor may hold signing
material, while Core must not receive a secret that could be extracted and used
to forge Monitor packages.

## Decision

Regulatory package schema version 2 uses Ed25519 signatures with domain
separation (`FinRadar regulatory package v2`). The signature covers the complete
canonical package, including package identifier, producer, creation/expiry
times, source evidence, payload checksum, algorithm, and key identifier. Only
the signature value itself is blanked while creating the signed bytes.

The neutral contract distribution depends on the narrow `cryptography` runtime
for Ed25519. It still contains no network or accounting runtime.

### Monitor private keys

- Private keys are generated with a cryptographic random generator and remain
  under the Monitor private-data directory.
- A key has a UUID, public-key fingerprint, `valid_from`, and `valid_until`.
- Key lifetime is limited to 366 days.
- On POSIX development systems the key directory is mode `0700` and private
  files are mode `0600`. On Windows the separate Monitor ACL is the enforcement
  layer.
- Metadata contains only the public key and fingerprint; loading derives the
  public key from the private material and verifies both.
- Activating a key outside its validity period is rejected.

The production installer should move private-key protection to Windows CNG,
DPAPI, or an HSM-backed provider when the deployment model is finalized. A
plain private-key file protected by the Monitor identity is acceptable for the
prototype boundary but is not the final key-custody mechanism.

### Core trust and rotation

Core stores public keys only. Trusted-key definitions and lifecycle events are
append-only and protected by SQLite immutability triggers.

The first key is initialized exactly once from a strict public-key record while
the signed installer runs under the protected Core identity. Re-running with
the byte-equivalent record is idempotent; any different key is rejected. Core
also rejects an initial key that is not currently valid. The ACL boundary must
exist before this step to avoid a local first-writer attack.

Rotation uses an overlap window:

1. Generate a new Monitor key.
2. Build a bounded rotation record containing the new public-key record and
   sign it with the current trusted private key under a separate rotation
   domain.
3. Verify the old key, signature, record lifetime, and unique rotation ID in
   Core before appending the new key.
4. Keep old and new keys trusted during a bounded overlap.
5. Activate the new Monitor key.
6. Revoke the old key in Core after all outstanding packages have expired.

Revocation is irreversible. Packages presented after revocation are rejected,
even when signed before the revocation event. An inbound regulatory package can
never add its own key to the trust store.

### Package lifetime

- Default lifetime is 48 hours.
- The schema rejects lifetimes above seven days.
- Core rejects expired packages and creation times more than five minutes in
  the future.
- The signing key must have been valid at the package creation time.

### Quarantine and replay protection

Core reads a bounded regular JSON file once, hashes those exact bytes, and then
performs structural, lifetime, trust, and signature checks.

- Accepted bytes are copied to the Core-owned accepted archive.
- Malformed, untrusted, expired, revoked, invalid-signature, and replayed bytes
  are copied to quarantine.
- Oversized files and symbolic links are not read or archived, but the rejected
  attempt is still recorded.
- Accepted package identifiers are unique. A repeated identifier is quarantined
  and cannot create a second accepted record.
- Archive files are read-only on POSIX. Every later archive load recomputes the
  immutable content hash and detects modification.
- Accepted package archives have no automatic retention deletion.
- Replayed raw archives are retained for seven days by default; other
  quarantined bytes are retained for thirty days by default.
- Retention recomputes the original hash before deletion. Missing, tampered,
  symlinked, or escaped paths are recorded and not silently deleted.
- Deletion intent and completion are separate append-only archive events, while
  the original import audit row remains immutable.

Every attempt creates an append-only audit row containing outcome, reason code,
package/key identifiers when available, original name, content hash when safely
read, archive location, and receipt time. Accepted-package replay markers and
trusted-key history are also immutable.

## Security invariants

- Signature verification does not activate a fiscal rule. It authenticates only
  the public candidate package.
- Only `RegulatoryPackageImporter` is a trusted import path. The explicitly
  named untrusted parser performs structure inspection only.
- Core never sends company context, identifiers, or financial data to Monitor.
- Secret-looking fields such as `private_key`, `password`, `api_key`, and access
  tokens are forbidden recursively in outbound packages.
- Revocation and replay decisions occur before candidate mapping.

## Remaining work

- Execute initial trust provisioning through the signed installer on Windows.
- Verify Windows ACLs, cross-identity access, and firewall policy on the release
  VM.
- Replace file-based private-key custody if the final threat model requires CNG,
  DPAPI, or hardware-backed keys.
- Code-sign executables and installer artifacts.

No downloader may be enabled until the trust root and Windows acceptance checks
are complete.
