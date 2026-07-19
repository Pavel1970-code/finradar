# ADR-006: Regulatory Monitor trust boundary

- Status: Accepted
- Date: 2026-07-19
- Product: FinRadar

## Context

FinRadar Core processes confidential accounting facts, bank operations, payment
calendar entries, and forecasts. It must not have internet access. A separate
component must retrieve public Georgian fiscal and financial information without
being able to read company data.

A second Python module alone is not a physical security boundary. The design
must separate processes, storage, network privileges, and the exchange format,
and the production installer must enforce the same separation with operating
system controls.

## Decision

The solution is split into three dependency zones:

1. `finradar` is the offline Core. It owns financial data and calculations and
   has no network-client dependency.
2. `finradar_monitor` is a separate executable. It owns only public regulatory
   documents and extracted public candidate rules. It must not import Core.
3. `finradar_contracts` is a neutral contract package. Its only external
   dependency is the cryptographic implementation used for Ed25519 signatures;
   it contains no runtime access to either component.

These zones are now separate Python distributions. Core and Monitor each depend
on the neutral contract wheel; neither wheel embeds the other runtime. Windows
PyInstaller specifications perform dependency-graph checks during each build and
do not use merged/mutually dependent executable bundles.

There is no Core-to-Monitor API or request containing company context. The only
planned exchange is a one-way, bounded JSON package:

```text
official HTTPS sources -> Monitor -> public candidate package -> Core validator
                                                             -> rule registry
                                                             -> local comparison
```

The package contract:

- accepts only a versioned set of known fields;
- limits the package, source, candidate, and evidence sizes;
- rejects duplicate JSON keys, unexpected fields, and known financial fields;
- requires official HTTPS source URLs from an explicit host allowlist;
- links every candidate to source evidence;
- verifies a canonical SHA-256 payload checksum and an Ed25519 producer
  signature;
- contains public candidate data only, never accounting data;
- cannot activate a rule. Existing lifecycle checks still require validation,
  review, and activation before deterministic calculations can use it.

The monitor uses `regulatory_monitor.db` and an outbox under a monitor-owned data
directory. It does not know the Core database path or schema. Core accepts a
single JSON file through its inbound validator; archives and executable content
are not part of the contract.

Every outbound URL and every redirect target must pass the same allowlist check.
The initial allowlist is limited to official Georgian sources under Matsne,
Revenue Service, Ministry of Finance, and National Bank domains. Adding a host
requires a reviewed code change.

## Threats and current controls

| Threat | Current control |
| --- | --- |
| Accidental financial-data egress | Core network-import policy; no Core-to-Monitor API; forbidden financial fields in packages |
| Monitor reading the Core database | Separate storage API and dependency-direction tests |
| Runtime accidentally packaged into the opposite executable | Separate distributions, wheel-content verifier, frozen dependency-graph assertions |
| Malicious or deceptive source URL | Exact hostname allowlist, HTTPS-only, no credentials, port 443 only |
| Redirect to an untrusted host | Policy requires revalidation after every redirect; downloader is not implemented yet |
| Oversized or malformed inbound data | Byte and item limits, strict JSON shape, duplicate-key rejection |
| Corrupted or replaced package | Canonical SHA-256 plus Ed25519 signature against a Core-owned trust store |
| AI-generated rule entering a forecast | Candidate-only import plus deterministic registry lifecycle |
| Public document containing active content | JSON-only exchange; no archive or executable import |

## Deployment controls prepared but not yet Windows-verified

- Windows build specifications create independent Core and Monitor directories
  and fail on forbidden runtime dependencies. PyInstaller is not a
  cross-compiler, so these builds still require a Windows runner.
- Provisioning scripts create a dedicated non-admin Monitor identity and an S4U
  scheduled task without retaining its generated password.
- Protected ACL templates give Monitor no Core-data access, give Core no
  Monitor-data access, and expose a separate Monitor-write/Core-read exchange.
- Firewall templates block Core public-internet destinations while retaining
  local accounting connectors. Monitor is blocked from local/intranet traffic,
  inbound traffic, UDP internet traffic, and non-HTTPS internet ports.
- Windows configuration and adversarial cross-identity tests must pass on the
  supported release VM before these prepared controls are considered enforced.

## Controls still required before enabling network access

- Define and implement raw quarantine retention; replay protection and immutable
  failed-import audit logs are implemented.
- Bootstrap the initial trusted public key through the signed installer.
- Code-sign both executables and the installer without storing signing keys in
  source control.
- Run the documented adversarial acceptance test proving Monitor cannot open a
  Core database and Core cannot establish a public-internet connection.

Network retrieval must remain disabled until these controls are implemented and
verified on the target Windows packaging environment.

Package authenticity, rotation, quarantine, and replay decisions are specified
in [ADR-007](ADR-007-signed-regulatory-ingestion.md).

## Consequences

- External rules can be compared with local accounting data only inside Core.
- Company context never needs to cross the internet boundary.
- The user interface can still present one forecast action; process separation
  is an implementation detail and does not require manual file handling.
- The repository now contains a verifiable code/process/storage/build boundary
  and Windows provisioning inputs, but it is not a completed production physical
  boundary until Windows acceptance tests and package authenticity pass.
