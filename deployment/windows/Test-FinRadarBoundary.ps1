[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateScript({ Test-Path $_ -PathType Leaf })]
    [string]$CoreExecutable,

    [Parameter(Mandatory = $true)]
    [ValidateScript({ Test-Path $_ -PathType Leaf })]
    [string]$MonitorExecutable,

    [Parameter(Mandatory = $true)]
    [ValidateScript({ Test-Path $_ -PathType Container })]
    [string]$CoreDataDirectory,

    [Parameter(Mandatory = $true)]
    [ValidateScript({ Test-Path $_ -PathType Container })]
    [string]$MonitorDataDirectory,

    [Parameter(Mandatory = $true)]
    [ValidateScript({ Test-Path $_ -PathType Container })]
    [string]$ExchangeDirectory,

    [Parameter(Mandatory = $true)]
    [string]$CorePrincipal,

    [Parameter(Mandatory = $true)]
    [string]$MonitorPrincipal
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$Failures = [Collections.Generic.List[string]]::new()

function Test-ProtectedAcl {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string[]]$RequiredPrincipals,
        [Parameter(Mandatory = $true)][string[]]$ForbiddenPrincipals
    )

    $Acl = Get-Acl -Path $Path
    if (-not $Acl.AreAccessRulesProtected) {
        $Failures.Add("$Path still inherits filesystem permissions.")
    }
    $Allowed = @(
        $Acl.Access |
            Where-Object { $_.AccessControlType -eq "Allow" } |
            ForEach-Object { $_.IdentityReference.Value }
    )
    foreach ($Principal in $RequiredPrincipals) {
        if ($Allowed -notcontains $Principal) {
            $Failures.Add("$Path does not grant access to $Principal.")
        }
    }
    foreach ($Principal in $ForbiddenPrincipals) {
        if ($Allowed -contains $Principal) {
            $Failures.Add("$Path unexpectedly grants access to $Principal.")
        }
    }
}

Test-ProtectedAcl `
    -Path $CoreDataDirectory `
    -RequiredPrincipals @($CorePrincipal, "NT AUTHORITY\SYSTEM", "BUILTIN\Administrators") `
    -ForbiddenPrincipals @($MonitorPrincipal)
Test-ProtectedAcl `
    -Path $MonitorDataDirectory `
    -RequiredPrincipals @($MonitorPrincipal, "NT AUTHORITY\SYSTEM", "BUILTIN\Administrators") `
    -ForbiddenPrincipals @($CorePrincipal)
Test-ProtectedAcl `
    -Path $ExchangeDirectory `
    -RequiredPrincipals @($CorePrincipal, $MonitorPrincipal) `
    -ForbiddenPrincipals @()

$FirewallGroup = "FinRadar Boundary v1"
$ExpectedRules = @{
    "FinRadar Core - block public internet" = @{ Action = "Block"; Direction = "Outbound" }
    "FinRadar Monitor - block local networks" = @{ Action = "Block"; Direction = "Outbound" }
    "FinRadar Monitor - block non-HTTPS TCP" = @{ Action = "Block"; Direction = "Outbound" }
    "FinRadar Monitor - block internet UDP" = @{ Action = "Block"; Direction = "Outbound" }
    "FinRadar Monitor - allow HTTPS" = @{ Action = "Allow"; Direction = "Outbound" }
    "FinRadar Monitor - block inbound" = @{ Action = "Block"; Direction = "Inbound" }
}
$Rules = @(Get-NetFirewallRule -Group $FirewallGroup -ErrorAction SilentlyContinue)
foreach ($DisplayName in $ExpectedRules.Keys) {
    $MatchingRules = @($Rules | Where-Object { $_.DisplayName -eq $DisplayName })
    if ($MatchingRules.Count -ne 1) {
        $Failures.Add("Expected exactly one enabled firewall rule '$DisplayName'.")
    }
    elseif ($MatchingRules[0].Enabled -ne "True") {
        $Failures.Add("Firewall rule '$DisplayName' is disabled.")
    }
    elseif (
        $MatchingRules[0].Action -ne $ExpectedRules[$DisplayName].Action -or
        $MatchingRules[0].Direction -ne $ExpectedRules[$DisplayName].Direction
    ) {
        $Failures.Add("Firewall rule '$DisplayName' has the wrong action or direction.")
    }
}

$CorePath = (Resolve-Path $CoreExecutable).Path
$MonitorPath = (Resolve-Path $MonitorExecutable).Path
foreach ($Rule in $Rules) {
    $Application = $Rule | Get-NetFirewallApplicationFilter
    if ($Rule.DisplayName -like "FinRadar Core*" -and $Application.Program -ne $CorePath) {
        $Failures.Add("Core firewall rule targets the wrong executable.")
    }
    if ($Rule.DisplayName -like "FinRadar Monitor*" -and $Application.Program -ne $MonitorPath) {
        $Failures.Add("Monitor firewall rule targets the wrong executable.")
    }
}

$CoreInternetRule = $Rules |
    Where-Object { $_.DisplayName -eq "FinRadar Core - block public internet" }
if ($CoreInternetRule) {
    $Addresses = @($CoreInternetRule | Get-NetFirewallAddressFilter).RemoteAddress
    if ($Addresses -notcontains "Internet") {
        $Failures.Add("Core firewall rule does not target the Internet address class.")
    }
}

$MonitorHttpsRule = $Rules |
    Where-Object { $_.DisplayName -eq "FinRadar Monitor - allow HTTPS" }
if ($MonitorHttpsRule) {
    $PortFilter = $MonitorHttpsRule | Get-NetFirewallPortFilter
    if ($PortFilter.Protocol -ne "TCP" -or $PortFilter.RemotePort -notcontains "443") {
        $Failures.Add("Monitor HTTPS rule does not target TCP remote port 443.")
    }
}

if ($Failures.Count -gt 0) {
    $Message = "FinRadar boundary verification failed:`n - " + ($Failures -join "`n - ")
    throw $Message
}

Write-Host "FinRadar ACL and firewall configuration checks passed."
Write-Warning "Run the separate cross-identity access and network acceptance tests before release."
