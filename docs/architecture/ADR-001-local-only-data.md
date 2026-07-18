# ADR-001: Local-only financial data

- Status: Accepted
- Date: 2026-07-18
- Product: FinRadar

## Context

FinRadar processes accounting records, cash balances, future obligations,
tax-related information, and financial risk calculations.

This information is commercially sensitive. Customers must not be required
to transfer financial data to FinRadar, a third-party cloud, an analytics
service, or an external AI provider.

The central data-residency promise is:

> Business financial data never leaves infrastructure controlled by the customer.

## Decision

FinRadar is designed as a local-first and on-premise product.

The standalone application must perform its core functions without internet
access. It must not require a FinRadar account, cloud database, telemetry
service, external API, or remote calculation service.

Core financial calculations must always run locally.

## Standalone deployment

In standalone mode:

- FinRadar runs on the accountant's computer.
- Financial data is stored in a local SQLite database.
- The calculation engine runs in the same local application.
- No external network connection is required.
- No telemetry or crash data is transmitted.
- No external AI service receives financial data.
- Backups remain under customer control.

The production database must be encrypted before real financial data is used.

## On-premise deployment

In on-premise mode:

- Desktop clients operate only inside the company network.
- The application server is installed on company-controlled infrastructure.
- PostgreSQL is installed on the company server.
- API traffic remains inside the local network.
- n8n, when used, is installed locally.
- Internet access is not required for financial calculations.
- External cloud storage is prohibited by default.

A shared SQLite file must not be used as a multi-user database over a network
filesystem. Multi-user deployments require a local client-server database.

## Prohibited by default

The standalone application must not include or use:

- Firebase
- cloud-hosted PostgreSQL
- external HTTP APIs
- OpenAI or other external AI APIs for customer data
- external telemetry or analytics
- external crash reporting
- automatic cloud backups
- automatic uploads of logs or database files
- hidden update checks
- advertising or tracking SDKs

Any future exception requires:

1. A separate architecture decision record.
2. Explicit customer consent.
3. A documented list of transmitted fields.
4. A customer-controlled opt-in setting.
5. Proof that core functionality continues to work offline.

## Artificial intelligence

AI does not participate in financial calculations.

If AI explanation or regulatory retrieval is added, strict deployments must
use a model running on customer-controlled infrastructure.

Calculated financial data and raw accounting records must not be sent to an
external AI provider.

## Regulatory updates

Strict offline installations receive regulatory rule updates through signed
local update packages.

An optional update service may be considered later, but it must be isolated
from financial data and must not have access to the customer database.

## Encryption

The current prototype uses a plaintext SQLite database with fictional data.

Before real financial data is imported, FinRadar must add:

- full database encryption;
- operating-system protected key storage;
- encrypted local backups;
- automatic application locking;
- secure database export;
- documented recovery procedures.

Encryption keys must never be stored in the repository, application source
code, or next to the database file.

## Verification

The standalone release must be verifiable through:

- automated tests preventing accidental network-client dependencies;
- successful operation with internet access disabled;
- successful operation with outbound traffic blocked by the operating system;
- dependency review before each release;
- inspection of application network activity;
- confirmation that no customer database is included in build artifacts.

## Consequences

Advantages:

- Strong customer trust.
- Reduced exposure to cloud data breaches.
- Offline operation.
- Clear separation between calculations and optional integrations.
- Easier deployment in regulated or security-sensitive organizations.

Trade-offs:

- Customers are responsible for local infrastructure and backups.
- Multi-user installations require an on-premise server.
- Updates require a controlled delivery mechanism.
- Local AI may require additional customer hardware.
- Encryption and recovery increase implementation complexity .
