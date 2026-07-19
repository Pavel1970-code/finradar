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
4. Run `Test-FinRadarBoundary.ps1` with the same arguments.

The directories have intentionally different permissions:

| Directory | Core | Monitor | Administrators/System |
| --- | --- | --- | --- |
| Core data | Modify | None | Full control |
| Monitor public data | None | Modify | Full control |
| One-way exchange | Read | Modify | Full control |

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

The supplied verification script checks declared ACL and firewall state. A
release VM must additionally execute adversarial tests under the real identities:

- Monitor cannot open or enumerate the Core database directory.
- Core can read completed exchange packages but cannot modify Monitor storage.
- Core cannot connect to a public test endpoint.
- Monitor cannot connect to loopback, the local subnet, or non-HTTPS internet
  ports.
- Monitor can reach an approved official HTTPS test endpoint.
- Neither executable contains the other runtime package.

Do not enable the downloader until all checks pass on the supported Windows
build and the package-signing/quarantine slice is complete.
