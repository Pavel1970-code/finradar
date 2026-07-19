[CmdletBinding()]
param(
    [Parameter()]
    [string]$Python = "python",

    [Parameter()]
    [string]$OutputDirectory = "dist-windows"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw "FinRadar Windows artifacts must be built on Windows. PyInstaller is not a cross-compiler."
}

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$OutputRoot = Join-Path $ProjectRoot $OutputDirectory
$WorkRoot = Join-Path $OutputRoot "work"
$CoreOutput = Join-Path $OutputRoot "core"
$MonitorOutput = Join-Path $OutputRoot "monitor"

& $Python -c "import PyInstaller; import setuptools"
if ($LASTEXITCODE -ne 0) {
    throw "Install packaging/windows/requirements.txt in the isolated build environment first."
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --distpath $CoreOutput `
    --workpath (Join-Path $WorkRoot "core") `
    (Join-Path $PSScriptRoot "finradar-core.spec")
if ($LASTEXITCODE -ne 0) {
    throw "FinRadar Core build failed."
}

& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --distpath $MonitorOutput `
    --workpath (Join-Path $WorkRoot "monitor") `
    (Join-Path $PSScriptRoot "finradar-monitor.spec")
if ($LASTEXITCODE -ne 0) {
    throw "FinRadar Monitor build failed."
}

Write-Host "Independent artifacts created:"
Write-Host "  Core:    $CoreOutput"
Write-Host "  Monitor: $MonitorOutput"
