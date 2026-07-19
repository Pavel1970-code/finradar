[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$CoreDataDirectory,
    [Parameter(Mandatory = $true)][string]$MonitorDataDirectory,
    [Parameter(Mandatory = $true)][string]$ExchangeDirectory,
    [Parameter(Mandatory = $true)][string]$ReportPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$Results = [ordered]@{}

try {
    $null = Get-ChildItem -LiteralPath $CoreDataDirectory -ErrorAction Stop
    $Results.CoreDataDenied = $false
}
catch {
    $Results.CoreDataDenied = $true
}

$MonitorProbe = Join-Path $MonitorDataDirectory "monitor-identity.probe"
try {
    Set-Content -LiteralPath $MonitorProbe -Value "monitor" -NoNewline
    Remove-Item -LiteralPath $MonitorProbe -Force
    $Results.MonitorDataWritable = $true
}
catch {
    $Results.MonitorDataWritable = $false
}

$ExchangeProbe = Join-Path $ExchangeDirectory "monitor-exchange.probe"
try {
    Set-Content -LiteralPath $ExchangeProbe -Value "monitor" -NoNewline
    Remove-Item -LiteralPath $ExchangeProbe -Force
    $Results.ExchangeWritable = $true
}
catch {
    $Results.ExchangeWritable = $false
}

$Results | ConvertTo-Json -Compress | Set-Content -LiteralPath $ReportPath -Encoding UTF8
