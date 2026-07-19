from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WINDOWS_DEPLOYMENT = PROJECT_ROOT / "deployment" / "windows"


def test_windows_trust_bootstrap_uses_monitor_identity_and_public_record() -> None:
    script = (WINDOWS_DEPLOYMENT / "Initialize-FinRadarTrust.ps1").read_text(
        encoding="utf-8"
    )

    assert "--initialize-signing-key" in script
    assert "--public-key-record" in script
    assert "--bootstrap-regulatory-trust" in script
    assert "FINRADAR_CORE_DATA_DIR" in script
    assert "finally" in script
    assert "-Action $OriginalActions" in script


def test_windows_identity_acceptance_runs_core_with_limited_token() -> None:
    orchestrator = (
        WINDOWS_DEPLOYMENT / "Invoke-FinRadarIdentityAcceptance.ps1"
    ).read_text(encoding="utf-8")
    core_worker = (WINDOWS_DEPLOYMENT / "Test-FinRadarCoreIdentity.ps1").read_text(
        encoding="utf-8"
    )
    monitor_worker = (
        WINDOWS_DEPLOYMENT / "Test-FinRadarMonitorIdentity.ps1"
    ).read_text(encoding="utf-8")

    assert "-RunLevel Limited" in orchestrator
    assert "Unregister-ScheduledTask" in orchestrator
    assert "-Action $OriginalActions" in orchestrator
    assert "MonitorDataDenied" in core_worker
    assert "ExchangeWriteDenied" in core_worker
    assert "CoreDataDenied" in monitor_worker
    assert "ExchangeWritable" in monitor_worker
