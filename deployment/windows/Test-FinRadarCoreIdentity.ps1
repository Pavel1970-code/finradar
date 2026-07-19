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
    $null = Get-ChildItem -LiteralPath $MonitorDataDirectory -ErrorAction Stop
    $Results.MonitorDataDenied = $false
}
catch {
    $Results.MonitorDataDenied = $true
}

$CoreProbe = Join-Path $CoreDataDirectory "core-identity.probe"
try {
    Set-Content -LiteralPath $CoreProbe -Value "core" -NoNewline
    Remove-Item -LiteralPath $CoreProbe -Force
    $Results.CoreDataWritable = $true
}
catch {
    $Results.CoreDataWritable = $false
}

try {
    $null = Get-ChildItem -LiteralPath $ExchangeDirectory -ErrorAction Stop
    $Results.ExchangeReadable = $true
}
catch {
    $Results.ExchangeReadable = $false
}

$ExchangeProbe = Join-Path $ExchangeDirectory "core-exchange-write.probe"
try {
    Set-Content -LiteralPath $ExchangeProbe -Value "core" -NoNewline -ErrorAction Stop
    Remove-Item -LiteralPath $ExchangeProbe -Force -ErrorAction SilentlyContinue
    $Results.ExchangeWriteDenied = $false
}
catch {
    $Results.ExchangeWriteDenied = $true
}

$Results | ConvertTo-Json -Compress | Set-Content -LiteralPath $ReportPath -Encoding UTF8
