[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = "High")]
param(
    [Parameter(Mandatory = $true)]
    [ValidateScript({ Test-Path $_ -PathType Leaf })]
    [string]$MonitorExecutable,

    [Parameter(Mandatory = $true)]
    [string]$MonitorDataDirectory,

    [Parameter(Mandatory = $true)]
    [string]$ExchangeDirectory,

    [Parameter()]
    [ValidatePattern("^[A-Za-z0-9_-]{1,20}$")]
    [string]$LocalUserName = "FinRadarMonitorSvc",

    [Parameter()]
    [string]$TaskName = "FinRadar Regulatory Monitor"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$CurrentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
$AdministratorRole = [Security.Principal.WindowsBuiltInRole]::Administrator
$CurrentPrincipal = [Security.Principal.WindowsPrincipal]::new($CurrentIdentity)
if (-not $CurrentPrincipal.IsInRole($AdministratorRole)) {
    throw "Run this provisioning script from an elevated PowerShell session."
}

$ExistingUser = Get-LocalUser -Name $LocalUserName -ErrorAction SilentlyContinue
if (-not $ExistingUser) {
    if ($PSCmdlet.ShouldProcess($LocalUserName, "Create dedicated non-admin Monitor identity")) {
        $RandomBytes = New-Object byte[] 48
        $Generator = [Security.Cryptography.RandomNumberGenerator]::Create()
        try {
            $Generator.GetBytes($RandomBytes)
        }
        finally {
            $Generator.Dispose()
        }
        $RandomPassword = [Convert]::ToBase64String($RandomBytes)
        $SecurePassword = ConvertTo-SecureString $RandomPassword -AsPlainText -Force
        New-LocalUser `
            -Name $LocalUserName `
            -Password $SecurePassword `
            -AccountNeverExpires `
            -PasswordNeverExpires `
            -UserMayNotChangePassword `
            -Description "Restricted identity for FinRadar public regulatory monitoring" |
            Out-Null
        $RandomPassword = $null
        [Array]::Clear($RandomBytes, 0, $RandomBytes.Length)
    }
}

$MonitorPath = (Resolve-Path $MonitorExecutable).Path
$MonitorPrincipal = "$env:COMPUTERNAME\$LocalUserName"
$Arguments = @(
    "--data-directory `"$MonitorDataDirectory`""
    "--outbox-directory `"$ExchangeDirectory`""
) -join " "

if ($PSCmdlet.ShouldProcess($TaskName, "Register restricted Monitor scheduled task")) {
    $Action = New-ScheduledTaskAction -Execute $MonitorPath -Argument $Arguments
    $StartupTrigger = New-ScheduledTaskTrigger -AtStartup
    $DailyTrigger = New-ScheduledTaskTrigger -Daily -At "00:05"
    $DailyTrigger.Repetition.Interval = "PT6H"
    $DailyTrigger.Repetition.Duration = "P1D"
    $Principal = New-ScheduledTaskPrincipal `
        -UserId $MonitorPrincipal `
        -LogonType S4U `
        -RunLevel Limited
    $Settings = New-ScheduledTaskSettingsSet `
        -MultipleInstances IgnoreNew `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
        -StartWhenAvailable
    $Task = New-ScheduledTask `
        -Action $Action `
        -Trigger @($StartupTrigger, $DailyTrigger) `
        -Principal $Principal `
        -Settings $Settings
    Register-ScheduledTask -TaskName $TaskName -InputObject $Task -Force | Out-Null
}

Write-Host "Monitor principal: $MonitorPrincipal"
Write-Host "Use this value as -MonitorPrincipal when applying Set-FinRadarBoundary.ps1."
