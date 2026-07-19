[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = "High")]
param(
    [Parameter(Mandatory = $true)]
    [ValidateScript({ Test-Path $_ -PathType Leaf })]
    [string]$CoreExecutable,

    [Parameter(Mandatory = $true)]
    [ValidateScript({ Test-Path $_ -PathType Leaf })]
    [string]$MonitorExecutable,

    [Parameter(Mandatory = $true)]
    [string]$CoreDataDirectory,

    [Parameter(Mandatory = $true)]
    [string]$MonitorDataDirectory,

    [Parameter(Mandatory = $true)]
    [string]$ExchangeDirectory,

    [Parameter(Mandatory = $true)]
    [string]$CorePrincipal,

    [Parameter(Mandatory = $true)]
    [string]$MonitorPrincipal
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$CurrentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
$AdministratorRole = [Security.Principal.WindowsBuiltInRole]::Administrator
$CurrentPrincipal = [Security.Principal.WindowsPrincipal]::new($CurrentIdentity)
if (-not $CurrentPrincipal.IsInRole($AdministratorRole)) {
    throw "Run this provisioning script from an elevated PowerShell session."
}

function Assert-KnownPrincipal {
    param([Parameter(Mandatory = $true)][string]$Name)

    try {
        $Account = [Security.Principal.NTAccount]::new($Name)
        $null = $Account.Translate([Security.Principal.SecurityIdentifier])
    }
    catch {
        throw "Windows principal '$Name' does not exist. Create the service identity first."
    }
}

function New-ProtectedDirectoryAcl {
    param(
        [Parameter(Mandatory = $true)][string]$OwnerPrincipal,
        [Parameter(Mandatory = $true)][string]$OwnerRights,
        [Parameter()][string]$ReaderPrincipal
    )

    $Acl = [Security.AccessControl.DirectorySecurity]::new()
    $Acl.SetAccessRuleProtection($true, $false)
    $Inheritance = [Security.AccessControl.InheritanceFlags]"ContainerInherit, ObjectInherit"
    $Propagation = [Security.AccessControl.PropagationFlags]::None
    $Allow = [Security.AccessControl.AccessControlType]::Allow

    foreach ($Entry in @(
        @{ Principal = "NT AUTHORITY\SYSTEM"; Rights = "FullControl" },
        @{ Principal = "BUILTIN\Administrators"; Rights = "FullControl" },
        @{ Principal = $OwnerPrincipal; Rights = $OwnerRights }
    )) {
        $Rule = [Security.AccessControl.FileSystemAccessRule]::new(
            $Entry.Principal,
            [Security.AccessControl.FileSystemRights]$Entry.Rights,
            $Inheritance,
            $Propagation,
            $Allow
        )
        $null = $Acl.AddAccessRule($Rule)
    }

    if ($ReaderPrincipal) {
        $ReaderRule = [Security.AccessControl.FileSystemAccessRule]::new(
            $ReaderPrincipal,
            [Security.AccessControl.FileSystemRights]"ReadAndExecute, Synchronize",
            $Inheritance,
            $Propagation,
            $Allow
        )
        $null = $Acl.AddAccessRule($ReaderRule)
    }
    return $Acl
}

Assert-KnownPrincipal -Name $CorePrincipal
Assert-KnownPrincipal -Name $MonitorPrincipal
if ($CorePrincipal.Equals($MonitorPrincipal, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Core and Monitor must use different Windows principals."
}

$ResolvedDataDirectories = @(
    [IO.Path]::GetFullPath($CoreDataDirectory).TrimEnd("\")
    [IO.Path]::GetFullPath($MonitorDataDirectory).TrimEnd("\")
    [IO.Path]::GetFullPath($ExchangeDirectory).TrimEnd("\")
)
foreach ($Directory in $ResolvedDataDirectories) {
    $Root = [IO.Path]::GetPathRoot($Directory).TrimEnd("\")
    if ($Directory.Equals($Root, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to replace ACLs on filesystem root '$Directory'."
    }
}
for ($Left = 0; $Left -lt $ResolvedDataDirectories.Count; $Left++) {
    for ($Right = $Left + 1; $Right -lt $ResolvedDataDirectories.Count; $Right++) {
        $LeftPath = $ResolvedDataDirectories[$Left]
        $RightPath = $ResolvedDataDirectories[$Right]
        if (
            $LeftPath.Equals($RightPath, [StringComparison]::OrdinalIgnoreCase) -or
            $LeftPath.StartsWith("$RightPath\", [StringComparison]::OrdinalIgnoreCase) -or
            $RightPath.StartsWith("$LeftPath\", [StringComparison]::OrdinalIgnoreCase)
        ) {
            throw "Core, Monitor, and exchange directories must be separate non-nested paths."
        }
    }
}

$CorePath = (Resolve-Path $CoreExecutable).Path
$MonitorPath = (Resolve-Path $MonitorExecutable).Path
$CoreDataDirectory = $ResolvedDataDirectories[0]
$MonitorDataDirectory = $ResolvedDataDirectories[1]
$ExchangeDirectory = $ResolvedDataDirectories[2]
$Directories = $ResolvedDataDirectories
foreach ($Directory in $Directories) {
    if ($PSCmdlet.ShouldProcess($Directory, "Create protected FinRadar directory")) {
        New-Item -ItemType Directory -Force -Path $Directory | Out-Null
    }
}

if ($PSCmdlet.ShouldProcess($CoreDataDirectory, "Replace ACL with Core-only access")) {
    $Acl = New-ProtectedDirectoryAcl -OwnerPrincipal $CorePrincipal -OwnerRights "Modify"
    Set-Acl -Path $CoreDataDirectory -AclObject $Acl
}

if ($PSCmdlet.ShouldProcess($MonitorDataDirectory, "Replace ACL with Monitor-only access")) {
    $Acl = New-ProtectedDirectoryAcl -OwnerPrincipal $MonitorPrincipal -OwnerRights "Modify"
    Set-Acl -Path $MonitorDataDirectory -AclObject $Acl
}

if ($PSCmdlet.ShouldProcess($ExchangeDirectory, "Replace ACL with one-way exchange access")) {
    $Acl = New-ProtectedDirectoryAcl `
        -OwnerPrincipal $MonitorPrincipal `
        -OwnerRights "Modify" `
        -ReaderPrincipal $CorePrincipal
    Set-Acl -Path $ExchangeDirectory -AclObject $Acl
}

$FirewallGroup = "FinRadar Boundary v1"
if ($PSCmdlet.ShouldProcess($FirewallGroup, "Replace FinRadar firewall rules")) {
    Get-NetFirewallRule -Group $FirewallGroup -ErrorAction SilentlyContinue |
        Remove-NetFirewallRule -ErrorAction Stop

    New-NetFirewallRule `
        -DisplayName "FinRadar Core - block public internet" `
        -Group $FirewallGroup `
        -Direction Outbound `
        -Program $CorePath `
        -RemoteAddress Internet `
        -Action Block `
        -Profile Any | Out-Null

    New-NetFirewallRule `
        -DisplayName "FinRadar Monitor - block local networks" `
        -Group $FirewallGroup `
        -Direction Outbound `
        -Program $MonitorPath `
        -RemoteAddress LocalSubnet, Intranet `
        -Action Block `
        -Profile Any | Out-Null

    New-NetFirewallRule `
        -DisplayName "FinRadar Monitor - block non-HTTPS TCP" `
        -Group $FirewallGroup `
        -Direction Outbound `
        -Program $MonitorPath `
        -RemoteAddress Internet `
        -Protocol TCP `
        -RemotePort "1-442", "444-65535" `
        -Action Block `
        -Profile Any | Out-Null

    New-NetFirewallRule `
        -DisplayName "FinRadar Monitor - block internet UDP" `
        -Group $FirewallGroup `
        -Direction Outbound `
        -Program $MonitorPath `
        -RemoteAddress Internet `
        -Protocol UDP `
        -Action Block `
        -Profile Any | Out-Null

    New-NetFirewallRule `
        -DisplayName "FinRadar Monitor - allow HTTPS" `
        -Group $FirewallGroup `
        -Direction Outbound `
        -Program $MonitorPath `
        -RemoteAddress Internet `
        -Protocol TCP `
        -RemotePort 443 `
        -Action Allow `
        -Profile Any | Out-Null

    New-NetFirewallRule `
        -DisplayName "FinRadar Monitor - block inbound" `
        -Group $FirewallGroup `
        -Direction Inbound `
        -Program $MonitorPath `
        -Action Block `
        -Profile Any | Out-Null
}

Write-Host "FinRadar boundary provisioned."
Write-Host "Set FINRADAR_MONITOR_DATA_DIR for the Monitor to: $MonitorDataDirectory"
Write-Host "Set FINRADAR_REGULATORY_OUTBOX for the Monitor to: $ExchangeDirectory"
