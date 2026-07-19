[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = "High")]
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

    [Parameter()]
    [string]$MonitorTaskName = "FinRadar Regulatory Monitor"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$CurrentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
$AdministratorRole = [Security.Principal.WindowsBuiltInRole]::Administrator
$CurrentPrincipal = [Security.Principal.WindowsPrincipal]::new($CurrentIdentity)
if (-not $CurrentPrincipal.IsInRole($AdministratorRole)) {
    throw "Run trust initialization from an elevated PowerShell session."
}
if (-not $CurrentIdentity.Name.Equals($CorePrincipal, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Trust initialization must run as the configured Core principal '$CorePrincipal'."
}

$CorePath = (Resolve-Path $CoreExecutable).Path
$MonitorPath = (Resolve-Path $MonitorExecutable).Path
$CoreDataPath = (Resolve-Path $CoreDataDirectory).Path
$MonitorDataPath = (Resolve-Path $MonitorDataDirectory).Path
$ExchangePath = (Resolve-Path $ExchangeDirectory).Path
$TrustRecordPath = Join-Path $ExchangePath "initial-regulatory-trust.json"
$Task = Get-ScheduledTask -TaskName $MonitorTaskName -ErrorAction Stop
$OriginalActions = $Task.Actions

$BootstrapArguments = @(
    "--data-directory `"$MonitorDataPath`""
    "--outbox-directory `"$ExchangePath`""
    "--initialize-signing-key"
    "--public-key-record `"$TrustRecordPath`""
) -join " "

if ($PSCmdlet.ShouldProcess($MonitorTaskName, "Generate Monitor key and export public trust record")) {
    try {
        Stop-ScheduledTask -TaskName $MonitorTaskName -ErrorAction SilentlyContinue
        $BootstrapAction = New-ScheduledTaskAction `
            -Execute $MonitorPath `
            -Argument $BootstrapArguments
        Set-ScheduledTask `
            -TaskName $MonitorTaskName `
            -Action $BootstrapAction | Out-Null
        Start-ScheduledTask -TaskName $MonitorTaskName

        $Deadline = [DateTime]::UtcNow.AddSeconds(60)
        do {
            Start-Sleep -Milliseconds 250
            $TaskInfo = Get-ScheduledTaskInfo -TaskName $MonitorTaskName
            $CurrentTask = Get-ScheduledTask -TaskName $MonitorTaskName
        } while ($CurrentTask.State -eq "Running" -and [DateTime]::UtcNow -lt $Deadline)

        if ($CurrentTask.State -eq "Running") {
            throw "Monitor trust bootstrap did not finish within 60 seconds."
        }
        if ($TaskInfo.LastTaskResult -ne 0) {
            throw "Monitor trust bootstrap failed with task result $($TaskInfo.LastTaskResult)."
        }
        if (-not (Test-Path $TrustRecordPath -PathType Leaf)) {
            throw "Monitor did not produce the public trust record."
        }
    }
    finally {
        Set-ScheduledTask `
            -TaskName $MonitorTaskName `
            -Action $OriginalActions | Out-Null
    }
}

if ($PSCmdlet.ShouldProcess($CoreDataPath, "Persist Core data location for the current user")) {
    [Environment]::SetEnvironmentVariable(
        "FINRADAR_CORE_DATA_DIR",
        $CoreDataPath,
        [EnvironmentVariableTarget]::User
    )
    $env:FINRADAR_CORE_DATA_DIR = $CoreDataPath
}

if ($PSCmdlet.ShouldProcess($CorePath, "Bootstrap Core regulatory trust")) {
    $CoreArguments = @(
        "--bootstrap-regulatory-trust `"$TrustRecordPath`""
        "--bootstrap-source `"signed FinRadar Windows installer`""
    ) -join " "
    $Process = Start-Process `
        -FilePath $CorePath `
        -ArgumentList $CoreArguments `
        -Wait `
        -PassThru
    if ($Process.ExitCode -ne 0) {
        throw "Core trust bootstrap failed with exit code $($Process.ExitCode)."
    }
}

Write-Host "FinRadar regulatory trust initialized."
Write-Host "The Monitor private key remains under: $MonitorDataPath"
Write-Host "Core imported only the public record from: $TrustRecordPath"
