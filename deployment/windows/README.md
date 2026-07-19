# Windows trust-boundary provisioning

These scripts are installer inputs, not a substitute for a signed installer.
Run them from an elevated PowerShell session on the target Windows version.

## Order

1. Build and code-sign the independent Core and Monitor artifacts.
2. Run `Install-FinRadarMonitorTask.ps1` to create the dedicated non-admin local
   identity and an S4U scheduled task. The task runs at startup and every six
   hours; it does not store the generated account password.
3. Run `Set-FinRadarBoundary.ps1` with the principal printed by step 2. It
   replaces inherited ACLs on the three data zones and creates scoped firewall
   rules.
4. Run `Initialize-FinRadarTrust.ps1` as the configured Core principal. It
   temporarily invokes the Monitor task under its S4U identity, creates one
   private signing key in Monitor storage, exports only a strict public record,
   and bootstraps the Core database. A retry with the same key is safe; a
   different first key is rejected.
5. Run `Test-FinRadarBoundary.ps1` with the same arguments.
6. Run `Invoke-FinRadarIdentityAcceptance.ps1`. It executes filesystem probes
   under the Monitor S4U identity and a temporary `RunLevel Limited` Core task.
   It restores the normal Monitor action and removes the temporary Core task
   even if a probe fails. Running the Core probe directly from the elevated
   installer would be invalid because Administrators intentionally retain
   recovery access to both data zones.

The ACL boundary must be applied before trust initialization. This prevents an
unprivileged first writer from creating the Core database and appointing an
untrusted initial key. The installer must itself be code-signed; these scripts
do not establish trust in an unsigned installer.

The directories have intentionally different permissions:

| Directory | Core | Monitor | Administrators/System |
| --- | --- | --- | --- |
| Core data | Modify | None | Full control |
| Monitor public data | None | Modify | Full control |
| One-way exchange | Read | Modify | Full control |

The Monitor private-data ACL also protects its signing-key directory. Core
stores only trusted public keys in its local database.

The firewall blocks Core access to addresses classified by Windows as
`Internet`, while leaving local/loopback accounting connectors possible. The
Monitor is blocked from local/intranet addresses, inbound traffic, UDP internet
traffic, and non-HTTPS TCP internet ports. Its application allowlist still
restricts HTTPS destinations to official Georgian hosts.

Windows Firewall cannot provide a portable per-program "deny every domain
except these FQDNs" policy without affecting the machine-wide outbound policy.
Therefore both layers are required: OS port/network-zone isolation and the exact
application hostname allowlist.

## Release acceptance tests

The supplied scripts check declared ACL/firewall state and real cross-identity
filesystem access. A release VM must additionally execute executable-level
network tests:

- Core cannot connect to a public test endpoint.
- Monitor cannot connect to loopback, the local subnet, or non-HTTPS internet
  ports.
- Monitor can reach an approved official HTTPS test endpoint.
- Neither executable contains the other runtime package.

The current Monitor has no downloader or network probe, so the positive and
negative executable network tests cannot yet be honestly executed. Static
firewall checks are not a substitute for those release tests.

Do not enable the downloader until all checks pass on the supported Windows
build and the initial trusted public key has been provisioned through the signed
installer.
