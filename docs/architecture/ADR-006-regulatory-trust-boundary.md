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
3. `finradar_contracts` is a standard-library-only neutral contract package.
   It contains no runtime access to either component.

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
- verifies a canonical SHA-256 payload checksum;
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
| Malicious or deceptive source URL | Exact hostname allowlist, HTTPS-only, no credentials, port 443 only |
| Redirect to an untrusted host | Policy requires revalidation after every redirect; downloader is not implemented yet |
| Oversized or malformed inbound data | Byte and item limits, strict JSON shape, duplicate-key rejection |
| Corrupted package | Canonical payload SHA-256 check |
| AI-generated rule entering a forecast | Candidate-only import plus deterministic registry lifecycle |
| Public document containing active content | JSON-only exchange; no archive or executable import |

## Controls still required before enabling network access

- Build and install Core and Monitor as separate artifacts rather than relying
  only on two entry points in the development package.
- Run Monitor under a distinct Windows service or user identity.
- Apply filesystem ACLs so Monitor cannot read the Core database and Core can
  read only completed package files from the exchange directory.
- Apply outbound firewall rules: deny Core; allow Monitor only to approved
  destinations. Application allowlists remain a second layer, not a substitute.
- Add package authenticity (signed manifest and trusted key rotation). SHA-256
  detects corruption but does not prove who produced a package.
- Define quarantine, replay protection, retention, and failed-import audit logs.
- Add an adversarial installer test proving Monitor cannot open a Core database
  and Core cannot establish an outbound connection.

Network retrieval must remain disabled until these controls are implemented and
verified on the target Windows packaging environment.

## Consequences

- External rules can be compared with local accounting data only inside Core.
- Company context never needs to cross the internet boundary.
- The user interface can still present one forecast action; process separation
  is an implementation detail and does not require manual file handling.
- The development scaffold is a verifiable code/process/storage boundary, but
  it is not yet the complete production physical boundary.
