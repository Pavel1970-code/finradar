[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateScript({ Test-Path $_ -PathType Container })]
    [string]$CoreDataDirectory,
    [Parameter(Mandatory = $true)]
    [ValidateScript({ Test-Path $_ -PathType Container })]
    [string]$MonitorDataDirectory,
    [Parameter(Mandatory = $true)]
    [ValidateScript({ Test-Path $_ -PathType Container })]
    [string]$ExchangeDirectory,
    [Parameter(Mandatory = $true)][string]$CorePrincipal,
    [Parameter()][string]$MonitorTaskName = "FinRadar Regulatory Monitor"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$CurrentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
$AdministratorRole = [Security.Principal.WindowsBuiltInRole]::Administrator
$CurrentPrincipal = [Security.Principal.WindowsPrincipal]::new($CurrentIdentity)
if (-not $CurrentPrincipal.IsInRole($AdministratorRole)) {
    throw "Run identity acceptance from an elevated PowerShell session."
}
if (-not $CurrentIdentity.Name.Equals($CorePrincipal, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Identity acceptance must run as the configured Core principal '$CorePrincipal'."
}

$ScriptPath = Join-Path $PSScriptRoot "Test-FinRadarMonitorIdentity.ps1"
$ReportPath = Join-Path $ExchangeDirectory "monitor-identity-acceptance.json"
$Task = Get-ScheduledTask -TaskName $MonitorTaskName -ErrorAction Stop
$OriginalActions = $Task.Actions
$WorkerArguments = @(
    "-NoProfile"
    "-NonInteractive"
    "-ExecutionPolicy Bypass"
    "-File `"$ScriptPath`""
    "-CoreDataDirectory `"$CoreDataDirectory`""
    "-MonitorDataDirectory `"$MonitorDataDirectory`""
    "-ExchangeDirectory `"$ExchangeDirectory`""
    "-ReportPath `"$ReportPath`""
) -join " "

try {
    Stop-ScheduledTask -TaskName $MonitorTaskName -ErrorAction SilentlyContinue
    $WorkerAction = New-ScheduledTaskAction `
        -Execute "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" `
        -Argument $WorkerArguments
    Set-ScheduledTask -TaskName $MonitorTaskName -Action $WorkerAction | Out-Null
    Start-ScheduledTask -TaskName $MonitorTaskName
    $Deadline = [DateTime]::UtcNow.AddSeconds(60)
    do {
        Start-Sleep -Milliseconds 250
        $CurrentTask = Get-ScheduledTask -TaskName $MonitorTaskName
    } while ($CurrentTask.State -eq "Running" -and [DateTime]::UtcNow -lt $Deadline)
    if ($CurrentTask.State -eq "Running" -or -not (Test-Path $ReportPath -PathType Leaf)) {
        throw "Monitor identity acceptance did not produce a report within 60 seconds."
    }
}
finally {
    Set-ScheduledTask -TaskName $MonitorTaskName -Action $OriginalActions | Out-Null
}

$Result = Get-Content -LiteralPath $ReportPath -Raw | ConvertFrom-Json
Remove-Item -LiteralPath $ReportPath -Force
if (-not $Result.CoreDataDenied) {
    throw "Monitor identity could enumerate Core data."
}
if (-not $Result.MonitorDataWritable) {
    throw "Monitor identity could not write its private data directory."
}
if (-not $Result.ExchangeWritable) {
    throw "Monitor identity could not write the exchange directory."
}

$CoreScriptPath = Join-Path $PSScriptRoot "Test-FinRadarCoreIdentity.ps1"
$CoreReportPath = Join-Path $CoreDataDirectory "core-identity-acceptance.json"
$CoreTaskName = "FinRadar Core Identity Acceptance (temporary)"
if (Get-ScheduledTask -TaskName $CoreTaskName -ErrorAction SilentlyContinue) {
    throw "Temporary Core acceptance task already exists; refusing to replace it."
}
$CoreWorkerArguments = @(
    "-NoProfile"
    "-NonInteractive"
    "-ExecutionPolicy Bypass"
    "-File `"$CoreScriptPath`""
    "-CoreDataDirectory `"$CoreDataDirectory`""
    "-MonitorDataDirectory `"$MonitorDataDirectory`""
    "-ExchangeDirectory `"$ExchangeDirectory`""
    "-ReportPath `"$CoreReportPath`""
) -join " "
$CoreTaskCreated = $false
try {
    $CoreAction = New-ScheduledTaskAction `
        -Execute "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" `
        -Argument $CoreWorkerArguments
    $CoreTaskPrincipal = New-ScheduledTaskPrincipal `
        -UserId $CorePrincipal `
        -LogonType Interactive `
        -RunLevel Limited
    $CoreSettings = New-ScheduledTaskSettingsSet `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 2)
    $CoreTask = New-ScheduledTask `
        -Action $CoreAction `
        -Principal $CoreTaskPrincipal `
        -Settings $CoreSettings
    Register-ScheduledTask `
        -TaskName $CoreTaskName `
        -InputObject $CoreTask | Out-Null
    $CoreTaskCreated = $true
    Start-ScheduledTask -TaskName $CoreTaskName
    $CoreDeadline = [DateTime]::UtcNow.AddSeconds(60)
    do {
        Start-Sleep -Milliseconds 250
        $CurrentCoreTask = Get-ScheduledTask -TaskName $CoreTaskName
    } while (
        $CurrentCoreTask.State -eq "Running" -and
        [DateTime]::UtcNow -lt $CoreDeadline
    )
    if (
        $CurrentCoreTask.State -eq "Running" -or
        -not (Test-Path $CoreReportPath -PathType Leaf)
    ) {
        throw "Limited Core identity acceptance did not produce a report within 60 seconds."
    }
}
finally {
    if ($CoreTaskCreated) {
        Unregister-ScheduledTask -TaskName $CoreTaskName -Confirm:$false
    }
}

$CoreResult = Get-Content -LiteralPath $CoreReportPath -Raw | ConvertFrom-Json
Remove-Item -LiteralPath $CoreReportPath -Force
if (-not $CoreResult.MonitorDataDenied) {
    throw "Limited Core identity could enumerate Monitor private data."
}
if (-not $CoreResult.CoreDataWritable) {
    throw "Limited Core identity could not write its own data directory."
}
if (-not $CoreResult.ExchangeReadable) {
    throw "Limited Core identity could not read the one-way exchange."
}
if (-not $CoreResult.ExchangeWriteDenied) {
    throw "Limited Core identity could write the one-way exchange directory."
}

Write-Host "FinRadar cross-identity filesystem acceptance checks passed."
Write-Warning "Executable network behavior still requires a Windows release-VM test."
